// CCWHAT MANAGED OPENCODE RUNTIME TASK COMMAND v1
async function callController(action, body = {}) {
  const port = process.env.CCWHAT_RUNTIME_CONTROL_PORT
  const token = process.env.CCWHAT_RUNTIME_TOKEN || ""
  if (!port) return null
  const response = await fetch(`http://127.0.0.1:${port}/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CCWhat-Run-Token": token,
    },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    console.error(`CCWhat ${action} failed:`, payload.error)
    return null
  }
  return payload.data || {}
}

export default async function ccwhatRuntimePlugin() {
  return {
    "command.execute.before": async (input, output) => {
      const actions = {
        "ccwhat:start": "start",
        "ccwhat:finish": "finish",
        "ccwhat-start": "start",
        "ccwhat-finish": "finish",
      }
      const action = actions[input.command]
      if (!action) return
      const data = await callController(action, {
        agent: "opencode",
        integration: "opencode_command_execute_before",
      })
      if (data) {
        console.error(`CCWhat ${action} recorded locally${data.task_id ? ` (${data.task_id})` : ""}.`)
      }
    },
  }
}
