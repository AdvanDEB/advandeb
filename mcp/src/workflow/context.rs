use std::collections::HashMap;

use serde_json::Value;

/// Execution context: maps step IDs to their result values.
#[derive(Debug, Default)]
pub struct WorkflowContext {
    results: HashMap<String, Value>,
}

impl WorkflowContext {
    pub fn insert(&mut self, step_id: String, value: Value) {
        self.results.insert(step_id, value);
    }

    pub fn get(&self, step_id: &str) -> Option<&Value> {
        self.results.get(step_id)
    }

    /// Recursively walk `value` and replace string leaves that match
    /// `"${stepId}"` or `"${stepId.field.subfield}"` with the
    /// corresponding value from the context.
    ///
    /// Returns an error if the referenced step or field path is missing.
    pub fn resolve(&self, value: &Value) -> Result<Value, String> {
        match value {
            Value::String(s) => self.resolve_string(s),
            Value::Object(map) => {
                let mut out = serde_json::Map::new();
                for (k, v) in map {
                    out.insert(k.clone(), self.resolve(v)?);
                }
                Ok(Value::Object(out))
            }
            Value::Array(arr) => {
                let resolved: Result<Vec<_>, _> = arr.iter().map(|v| self.resolve(v)).collect();
                Ok(Value::Array(resolved?))
            }
            other => Ok(other.clone()),
        }
    }

    fn resolve_string(&self, s: &str) -> Result<Value, String> {
        // Check if the entire string is a placeholder
        if let Some(inner) = s.strip_prefix("${").and_then(|s| s.strip_suffix('}')) {
            return self.lookup_path(inner);
        }
        // Otherwise substitute inline placeholders and keep as string
        let mut result = s.to_string();
        let mut search_start = 0;
        while let Some(start) = result[search_start..].find("${") {
            let abs_start = search_start + start;
            if let Some(end) = result[abs_start..].find('}') {
                let abs_end = abs_start + end;
                let path = &result[abs_start + 2..abs_end];
                match self.lookup_path(path)? {
                    Value::String(v) => {
                        result.replace_range(abs_start..=abs_end, &v);
                        search_start = abs_start + v.len();
                    }
                    other => {
                        let stringified = other.to_string();
                        result.replace_range(abs_start..=abs_end, &stringified);
                        search_start = abs_start + stringified.len();
                    }
                }
            } else {
                break;
            }
        }
        Ok(Value::String(result))
    }

    /// Walk a dot-separated path like `"step1"` or `"step1.results.0"`.
    fn lookup_path(&self, path: &str) -> Result<Value, String> {
        let mut parts = path.splitn(2, '.');
        let step_id = parts.next().unwrap();
        let field_path = parts.next();

        let step_result = self
            .results
            .get(step_id)
            .ok_or_else(|| format!("Context variable '${{{path}}}': step '{step_id}' has no result yet"))?;

        match field_path {
            None => Ok(step_result.clone()),
            Some(fp) => navigate(step_result, fp)
                .ok_or_else(|| format!("Context variable '${{{path}}}': path '{fp}' not found in step '{step_id}' result")),
        }
    }
}

/// Traverse a dot-separated field path into a serde_json Value.
fn navigate(mut val: &Value, path: &str) -> Option<Value> {
    for segment in path.split('.') {
        val = if let Ok(idx) = segment.parse::<usize>() {
            val.get(idx)?
        } else {
            val.get(segment)?
        };
    }
    Some(val.clone())
}

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn resolve_plain_value_unchanged() {
        let ctx = WorkflowContext::default();
        let v = json!({"key": 42});
        assert_eq!(ctx.resolve(&v).unwrap(), v);
    }

    #[test]
    fn resolve_whole_string_placeholder() {
        let mut ctx = WorkflowContext::default();
        ctx.insert("step1".into(), json!(["a", "b"]));
        let result = ctx.resolve(&json!("${step1}")).unwrap();
        assert_eq!(result, json!(["a", "b"]));
    }

    #[test]
    fn resolve_nested_field_path() {
        let mut ctx = WorkflowContext::default();
        ctx.insert("s1".into(), json!({"ids": [1, 2, 3]}));
        let result = ctx.resolve(&json!("${s1.ids}")).unwrap();
        assert_eq!(result, json!([1, 2, 3]));
    }

    #[test]
    fn resolve_inline_string_interpolation() {
        let mut ctx = WorkflowContext::default();
        ctx.insert("q".into(), json!("DEB epidemiology"));
        let result = ctx.resolve(&json!("query: ${q}")).unwrap();
        assert_eq!(result, json!("query: DEB epidemiology"));
    }

    #[test]
    fn resolve_missing_step_returns_error() {
        let ctx = WorkflowContext::default();
        assert!(ctx.resolve(&json!("${missing}")).is_err());
    }

    #[test]
    fn resolve_object_recursively() {
        let mut ctx = WorkflowContext::default();
        ctx.insert("step1".into(), json!("hello"));
        let input = json!({"arg": "${step1}", "static": 99});
        let result = ctx.resolve(&input).unwrap();
        assert_eq!(result, json!({"arg": "hello", "static": 99}));
    }
}
