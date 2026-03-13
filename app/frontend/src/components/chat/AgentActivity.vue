<template>
  <div class="agent-activity">
    <h3 class="panel-title">Agent Activity</h3>

    <div v-if="agents.length === 0" class="idle-state">
      <p>No active agents</p>
    </div>

    <div
      v-for="agent in agents"
      :key="agent.name"
      class="agent-card"
    >
      <div class="agent-header">
        <div class="agent-name-row">
          <span :class="['status-dot', agent.status]"></span>
          <span class="agent-name">{{ agent.displayName }}</span>
        </div>
        <span v-if="agent.status === 'working'" class="elapsed">
          {{ getElapsed(agent.startedAt) }}s
        </span>
      </div>

      <!-- Working state -->
      <div v-if="agent.status === 'working'" class="agent-working">
        <div class="task-row">
          <span class="spinner-inline"></span>
          <span class="task-label">{{ agent.currentTask || 'Processing…' }}</span>
        </div>
      </div>

      <!-- Completed state -->
      <div v-if="agent.status === 'completed'" class="agent-done">
        ✓ {{ agent.resultSummary || 'Done' }}
      </div>

      <!-- Error state -->
      <div v-if="agent.status === 'error'" class="agent-error">
        ✗ Error occurred
      </div>
    </div>

    <!-- Workflow trace -->
    <div v-if="workflowTrace.length > 0" class="workflow-trace">
      <h4 class="trace-title">Workflow Trace</h4>
      <ol class="trace-list">
        <li v-for="(step, idx) in workflowTrace" :key="idx" class="trace-step">
          <span class="trace-num">{{ idx + 1 }}.</span>
          <span class="trace-agent">{{ step.agent }}</span>:
          <span class="trace-action">{{ step.action }}</span>
        </li>
      </ol>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface AgentStatus {
  name: string
  displayName: string
  status: 'idle' | 'working' | 'completed' | 'error'
  currentTask?: string
  resultSummary?: string
  startedAt?: number
}

interface WorkflowStep {
  agent: string
  action: string
  timestamp: number
}

defineProps<{
  agents: AgentStatus[]
  workflowTrace: WorkflowStep[]
}>()

const now = ref(Date.now())

// Update elapsed timers every second
setInterval(() => { now.value = Date.now() }, 1000)

function getElapsed(startedAt?: number): string {
  if (!startedAt) return '0'
  return ((now.value - startedAt) / 1000).toFixed(1)
}
</script>

<style scoped>
.agent-activity {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.5rem;
}

.idle-state {
  color: #9ca3af;
  font-size: 0.8rem;
  text-align: center;
  padding: 1rem 0;
}

.agent-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.agent-name-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.idle { background: #9ca3af; }
.status-dot.working { background: #3b82f6; animation: pulse 1.4s ease-in-out infinite; }
.status-dot.completed { background: #10b981; }
.status-dot.error { background: #ef4444; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.agent-name {
  font-size: 0.8rem;
  font-weight: 500;
}

.elapsed {
  font-size: 0.75rem;
  color: #6b7280;
}

.agent-working {
  margin-top: 0.35rem;
}

.task-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.spinner-inline {
  width: 12px;
  height: 12px;
  border: 2px solid #d1d5db;
  border-top-color: #3b82f6;
  border-radius: 50%;
  display: inline-block;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.task-label {
  font-size: 0.75rem;
  color: #4b5563;
}

.agent-done {
  margin-top: 0.35rem;
  font-size: 0.75rem;
  color: #059669;
}

.agent-error {
  margin-top: 0.35rem;
  font-size: 0.75rem;
  color: #dc2626;
}

.workflow-trace {
  margin-top: 0.5rem;
  border-top: 1px solid #e5e7eb;
  padding-top: 0.75rem;
}

.trace-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.4rem;
}

.trace-list {
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.trace-step {
  font-size: 0.75rem;
  color: #6b7280;
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.trace-num {
  color: #9ca3af;
  font-variant-numeric: tabular-nums;
}

.trace-agent {
  font-weight: 500;
  color: #374151;
}

.trace-action {
  color: #6b7280;
}
</style>
