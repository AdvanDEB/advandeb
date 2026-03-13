use std::time::Duration;
use tokio::time::sleep;
use tracing::warn;

/// Retry `f` up to `max_retries` additional times (total attempts = `max_retries + 1`)
/// using truncated exponential backoff: 100ms, 200ms, 400ms, …, capped at 2s.
///
/// Only retries on transport-level errors (identified by the caller returning `Err`).
/// The caller is responsible for deciding whether a given error is retryable.
pub async fn retry_with_backoff<F, Fut, T>(
    mut f: F,
    max_retries: u32,
    context: &str,
) -> Result<T, anyhow::Error>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<T, anyhow::Error>>,
{
    let mut attempt = 0u32;
    loop {
        match f().await {
            Ok(val) => return Ok(val),
            Err(e) => {
                if attempt >= max_retries {
                    return Err(e);
                }
                let backoff_ms = (100u64 * 2u64.pow(attempt)).min(2000);
                warn!(
                    context,
                    attempt = attempt + 1,
                    max_retries,
                    backoff_ms,
                    error = %e,
                    "Retrying after error"
                );
                sleep(Duration::from_millis(backoff_ms)).await;
                attempt += 1;
            }
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicU32, Ordering},
        Arc,
    };

    #[tokio::test]
    async fn succeeds_first_try() {
        let result = retry_with_backoff(|| async { Ok::<i32, anyhow::Error>(42) }, 3, "test").await;
        assert_eq!(result.unwrap(), 42);
    }

    #[tokio::test]
    async fn retries_then_succeeds() {
        let calls = Arc::new(AtomicU32::new(0));
        let calls2 = Arc::clone(&calls);

        let result = retry_with_backoff(
            move || {
                let c = Arc::clone(&calls2);
                async move {
                    let n = c.fetch_add(1, Ordering::SeqCst);
                    if n < 2 {
                        Err(anyhow::anyhow!("transient error"))
                    } else {
                        Ok(n)
                    }
                }
            },
            3,
            "test",
        )
        .await;

        assert!(result.is_ok());
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn exhausts_retries_and_errors() {
        let calls = Arc::new(AtomicU32::new(0));
        let calls2 = Arc::clone(&calls);

        let result = retry_with_backoff(
            move || {
                let c = Arc::clone(&calls2);
                async move {
                    c.fetch_add(1, Ordering::SeqCst);
                    Err::<i32, _>(anyhow::anyhow!("always fails"))
                }
            },
            2,
            "test",
        )
        .await;

        assert!(result.is_err());
        // 1 initial + 2 retries = 3 total calls
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }
}
