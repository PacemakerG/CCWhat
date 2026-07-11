#!/bin/sh
# CCWHAT MANAGED RUNTIME TASK COMMAND v1
exec "${CCWHAT_PYTHON:-python3}" -m ccwhat.runtime.claude_hook
