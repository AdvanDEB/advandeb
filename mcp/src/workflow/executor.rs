use std::sync::Arc;
use std::time::Instant;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{info, warn};

use crate::gateway::router::AgentRouter;

use super::context::WorkflowContext;

/// One step in a workflow.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct WorkflowStep {
    /// Unique identifier for this step within the workflow.
    pub id: String,
    /// Tool name to call (must be registered with the gateway).
    pub tool: String,
    /// Arguments for the tool call. May contain `${stepId}` or
    /// `${stepId.field}` placeholders that are resolved from previous
    /// step results.
    #[serde(default)]
    pub arguments: Value,
}

/// A complete workflow definition.
#[derive(Debug, Deserialize)]
pub struct Workflow {
    pub steps: Vec<WorkflowStep>,
}

/// Per-step execution record returned in the workflow result.
#[derive(Debug, Serialize)]
pub struct StepRecord {
    pub id: String,
    pub tool: String,
    pub elapsed_ms: u128,
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Outcome of a `workflow/run` call.
#[derive(Debug, Serialize)]
pub struct WorkflowResult {
    pub steps: Vec<StepRecord>,
    pub total_elapsed_ms: u128,
    /// The result of the final step (convenience accessor).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_result: Option<Value>,
}

pub struct WorkflowExecutor {
    router: Arc<AgentRouter>,
}

impl WorkflowExecutor {
    pub fn new(router: Arc<AgentRouter>) -> Self {
        Self { router }
    }

    /// Execute the workflow steps in order.
    ///
    /// Steps run sequentially. Each step's result is stored in the context
    /// under its `id` and can be referenced in subsequent steps' arguments
    /// via `${id}` or `${id.field.path}` placeholders.
    ///
    /// On step failure the workflow aborts and returns an error describing
    /// which step failed.
    pub async fn run(&self, workflow: Workflow) -> Result<WorkflowResult, String> {
        let workflow_start = Instant::now();
        let mut ctx = WorkflowContext::default();
        let mut records: Vec<StepRecord> = Vec::with_capacity(workflow.steps.len());
        let mut final_result: Option<Value> = None;

        for step in workflow.steps {
            let step_start = Instant::now();

            // Resolve placeholders in arguments using context
            let resolved_args = match ctx.resolve(&step.arguments) {
                Ok(v) => v,
                Err(e) => {
                    warn!(step = %step.id, error = %e, "Argument resolution failed");
                    records.push(StepRecord {
                        id: step.id.clone(),
                        tool: step.tool.clone(),
                        elapsed_ms: step_start.elapsed().as_millis(),
                        status: "error",
                        result: None,
                        error: Some(e.clone()),
                    });
                    return Err(format!("Step '{}' argument resolution failed: {}", step.id, e));
                }
            };

            // Execute the tool call
            let call_result = self
                .router
                .route_tool_call(&step.tool, resolved_args)
                .await;

            let elapsed_ms = step_start.elapsed().as_millis();

            match call_result {
                Ok(result) => {
                    info!(
                        step = %step.id,
                        tool = %step.tool,
                        elapsed_ms,
                        "Workflow step succeeded"
                    );
                    ctx.insert(step.id.clone(), result.clone());
                    final_result = Some(result.clone());
                    records.push(StepRecord {
                        id: step.id,
                        tool: step.tool,
                        elapsed_ms,
                        status: "ok",
                        result: Some(result),
                        error: None,
                    });
                }
                Err(e) => {
                    warn!(
                        step = %step.id,
                        tool = %step.tool,
                        elapsed_ms,
                        error = %e,
                        "Workflow step failed"
                    );
                    records.push(StepRecord {
                        id: step.id.clone(),
                        tool: step.tool,
                        elapsed_ms,
                        status: "error",
                        result: None,
                        error: Some(e.to_string()),
                    });
                    return Err(format!("Step '{}' failed: {}", step.id, e));
                }
            }
        }

        Ok(WorkflowResult {
            steps: records,
            total_elapsed_ms: workflow_start.elapsed().as_millis(),
            final_result,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_workflow_step_deserialize() {
        let json = r#"{
            "id": "step1",
            "tool": "semantic_search",
            "arguments": {"query": "test"}
        }"#;
        
        let step: WorkflowStep = serde_json::from_str(json).unwrap();
        assert_eq!(step.id, "step1");
        assert_eq!(step.tool, "semantic_search");
        assert_eq!(step.arguments["query"], "test");
    }

    #[test]
    fn test_workflow_step_without_arguments() {
        let json = r#"{"id": "step1", "tool": "ping"}"#;
        
        let step: WorkflowStep = serde_json::from_str(json).unwrap();
        assert_eq!(step.id, "step1");
        assert_eq!(step.tool, "ping");
        assert_eq!(step.arguments, json!(null));
    }

    #[test]
    fn test_workflow_deserialize() {
        let json = r#"{
            "steps": [
                {"id": "s1", "tool": "search", "arguments": {"query": "test"}},
                {"id": "s2", "tool": "expand", "arguments": {"ids": "${s1.ids}"}}
            ]
        }"#;
        
        let workflow: Workflow = serde_json::from_str(json).unwrap();
        assert_eq!(workflow.steps.len(), 2);
        assert_eq!(workflow.steps[0].id, "s1");
        assert_eq!(workflow.steps[1].id, "s2");
    }

    #[test]
    fn test_step_record_serialize() {
        let record = StepRecord {
            id: "step1".to_string(),
            tool: "test_tool".to_string(),
            elapsed_ms: 100,
            status: "ok",
            result: Some(json!({"data": "result"})),
            error: None,
        };
        
        let serialized = serde_json::to_string(&record).unwrap();
        assert!(serialized.contains("\"status\":\"ok\""));
        assert!(serialized.contains("\"elapsed_ms\":100"));
        assert!(!serialized.contains("\"error\""));
    }

    #[test]
    fn test_step_record_error_serialize() {
        let record = StepRecord {
            id: "step1".to_string(),
            tool: "test_tool".to_string(),
            elapsed_ms: 50,
            status: "error",
            result: None,
            error: Some("Tool failed".to_string()),
        };
        
        let serialized = serde_json::to_string(&record).unwrap();
        assert!(serialized.contains("\"status\":\"error\""));
        assert!(serialized.contains("\"error\":\"Tool failed\""));
        assert!(!serialized.contains("\"result\""));
    }

    #[test]
    fn test_workflow_result_serialize() {
        let result = WorkflowResult {
            steps: vec![
                StepRecord {
                    id: "s1".to_string(),
                    tool: "search".to_string(),
                    elapsed_ms: 100,
                    status: "ok",
                    result: Some(json!({"ids": [1, 2, 3]})),
                    error: None,
                },
            ],
            total_elapsed_ms: 150,
            final_result: Some(json!({"ids": [1, 2, 3]})),
        };
        
        let serialized = serde_json::to_string(&result).unwrap();
        assert!(serialized.contains("\"total_elapsed_ms\":150"));
        assert!(serialized.contains("\"final_result\""));
    }

    #[test]
    fn test_workflow_step_serialize_deserialize() {
        let step = WorkflowStep {
            id: "test_step".to_string(),
            tool: "test_tool".to_string(),
            arguments: json!({"key": "value"}),
        };
        
        let serialized = serde_json::to_string(&step).unwrap();
        let deserialized: WorkflowStep = serde_json::from_str(&serialized).unwrap();
        
        assert_eq!(deserialized.id, "test_step");
        assert_eq!(deserialized.tool, "test_tool");
        assert_eq!(deserialized.arguments, json!({"key": "value"}));
    }
}
