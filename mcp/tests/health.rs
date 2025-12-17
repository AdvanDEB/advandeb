use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use tower::ServiceExt;

fn app() -> axum::Router {
    let settings = advandeb_mcp::config::Settings::load().unwrap();
    let state = advandeb_mcp::build_state(settings).unwrap();
    advandeb_mcp::build_router(state)
}

#[tokio::test]
async fn health_ok() {
    let app = app();
    let response = app
        .clone()
        .oneshot(Request::builder().uri("/health").body(Body::empty()).unwrap())
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["status"], "ok");
    assert!(json["ollama_model"].is_string());
}
