#!/bin/bash
# Verify KB Chat request/response payload

set -e

QUESTION="How do I sync Google contacts?"

echo "Testing KB Chat endpoint with question: '$QUESTION'"
echo
echo "Expected Request Payload:"
echo '{"query":"How do I sync Google contacts?"}'
echo
echo "Making request to http://localhost:3001/api/kb-chat..."
echo

# Note: This requires a valid session cookie from browser
# For automated testing, you would need to login first
curl -X POST http://localhost:3001/api/kb-chat \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"$QUESTION\"}" \
  -w "\n\nHTTP Status: %{http_code}\n" \
  2>&1

echo
echo "================================"
echo "To test from browser:"
echo "1. Open DevTools (F12) → Network tab"
echo "2. Navigate to http://localhost:5173/kb-chat"
echo "3. Login if needed"
echo "4. Enter: $QUESTION"
echo "5. Click 'Ask Question'"
echo "6. Check the 'kb-chat' request in Network tab"
echo "7. Verify Request Payload shows: {\"query\":\"...\"}"
echo "================================"
