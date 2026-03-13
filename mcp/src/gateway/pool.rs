use std::{
    collections::{HashMap, VecDeque},
    sync::Arc,
};

use tokio::net::TcpStream;
use tokio::sync::Mutex;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream, connect_async};
use tracing::{debug, warn};

/// A pooled WebSocket stream to an agent.
pub type WsStream = WebSocketStream<MaybeTlsStream<TcpStream>>;

/// Maximum idle connections kept per agent URL.
const MAX_IDLE_PER_AGENT: usize = 5;

/// Connection pool for outbound agent WebSocket connections.
///
/// On each tool call the router checks out an idle connection; on success it
/// checks the connection back in.  Broken connections (on error) are simply
/// dropped rather than returned.
#[derive(Clone)]
pub struct ConnectionPool {
    idle: Arc<Mutex<HashMap<String, VecDeque<WsStream>>>>,
}

impl ConnectionPool {
    pub fn new() -> Self {
        Self {
            idle: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Check out a connection for `url`.
    ///
    /// Returns an existing idle connection when available, otherwise opens a
    /// fresh one.
    pub async fn acquire(&self, url: &str) -> Result<WsStream, anyhow::Error> {
        {
            let mut pool = self.idle.lock().await;
            if let Some(queue) = pool.get_mut(url) {
                if let Some(conn) = queue.pop_front() {
                    debug!("Reusing pooled connection to {url}");
                    return Ok(conn);
                }
            }
        }

        debug!("Opening new connection to {url}");
        let (stream, _) = connect_async(url)
            .await
            .map_err(|e| anyhow::anyhow!("Failed to connect to agent at {}: {}", url, e))?;
        Ok(stream)
    }

    /// Return a healthy connection to the pool after a successful tool call.
    pub async fn release(&self, url: String, conn: WsStream) {
        let mut pool = self.idle.lock().await;
        let queue = pool.entry(url.clone()).or_default();
        if queue.len() < MAX_IDLE_PER_AGENT {
            queue.push_back(conn);
            debug!("Returned connection to pool for {url}");
        } else {
            warn!("Pool full for {url}, dropping connection");
        }
    }

    /// Current number of idle connections across all agents (for metrics/debug).
    pub async fn idle_count(&self) -> usize {
        self.idle.lock().await.values().map(|q| q.len()).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;
    use tokio_tungstenite::accept_async;

    /// Helper: spawn a mock WebSocket server on a random port
    async fn spawn_mock_ws_server() -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        
        tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                tokio::spawn(async move {
                    let _ = accept_async(stream).await;
                    // Just accept and hold the connection
                    tokio::time::sleep(tokio::time::Duration::from_secs(60)).await;
                });
            }
        });
        
        format!("ws://127.0.0.1:{}", addr.port())
    }

    #[tokio::test]
    async fn test_pool_new() {
        let pool = ConnectionPool::new();
        assert_eq!(pool.idle_count().await, 0);
    }

    #[tokio::test]
    async fn test_acquire_creates_new_connection() {
        let pool = ConnectionPool::new();
        let url = spawn_mock_ws_server().await;
        
        let conn = pool.acquire(&url).await;
        assert!(conn.is_ok(), "Should successfully connect to mock server");
        assert_eq!(pool.idle_count().await, 0, "New connection should not be in pool yet");
    }

    #[tokio::test]
    async fn test_release_adds_to_pool() {
        let pool = ConnectionPool::new();
        let url = spawn_mock_ws_server().await;
        
        let conn = pool.acquire(&url).await.unwrap();
        pool.release(url.clone(), conn).await;
        
        assert_eq!(pool.idle_count().await, 1, "Released connection should be in pool");
    }

    #[tokio::test]
    async fn test_acquire_reuses_pooled_connection() {
        let pool = ConnectionPool::new();
        let url = spawn_mock_ws_server().await;
        
        // First acquire and release
        let conn1 = pool.acquire(&url).await.unwrap();
        pool.release(url.clone(), conn1).await;
        assert_eq!(pool.idle_count().await, 1);
        
        // Second acquire should reuse the pooled connection
        let _conn2 = pool.acquire(&url).await.unwrap();
        assert_eq!(pool.idle_count().await, 0, "Pooled connection should be reused");
    }

    #[tokio::test]
    async fn test_pool_respects_max_idle_limit() {
        let pool = ConnectionPool::new();
        let url = spawn_mock_ws_server().await;
        
        // Acquire and hold MAX_IDLE_PER_AGENT + 2 connections simultaneously
        let mut connections = Vec::new();
        for _ in 0..(MAX_IDLE_PER_AGENT + 2) {
            let conn = pool.acquire(&url).await.unwrap();
            connections.push(conn);
        }
        
        // Now release all of them
        for conn in connections {
            pool.release(url.clone(), conn).await;
        }
        
        assert_eq!(
            pool.idle_count().await,
            MAX_IDLE_PER_AGENT,
            "Pool should not exceed MAX_IDLE_PER_AGENT limit"
        );
    }

    #[tokio::test]
    async fn test_multiple_agents_in_pool() {
        let pool = ConnectionPool::new();
        let url1 = spawn_mock_ws_server().await;
        let url2 = spawn_mock_ws_server().await;
        
        let conn1 = pool.acquire(&url1).await.unwrap();
        let conn2 = pool.acquire(&url2).await.unwrap();
        
        pool.release(url1.clone(), conn1).await;
        pool.release(url2.clone(), conn2).await;
        
        assert_eq!(pool.idle_count().await, 2, "Pool should track connections for both agents");
    }

    #[tokio::test]
    async fn test_acquire_invalid_url() {
        let pool = ConnectionPool::new();
        let result = pool.acquire("ws://invalid.invalid:9999").await;
        
        assert!(result.is_err(), "Should fail to connect to invalid URL");
    }
}
