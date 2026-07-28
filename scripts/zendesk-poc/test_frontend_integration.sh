#!/bin/bash
# Test KB Chat Frontend Integration
#
# This script:
# 1. Checks that the vite dev server is running (port 5173)
# 2. Checks that the backend server is running (port 3001)
# 3. Tests the KB chat API endpoint
# 4. Provides instructions for manual browser testing

set -e

echo "======================================================================"
echo "KB CHAT FRONTEND INTEGRATION TEST"
echo "======================================================================"
echo

# Check vite dev server
echo "1. Checking Vite dev server (port 5173)..."
if curl -s -f http://localhost:5173 > /dev/null; then
    echo "   ✅ Vite dev server is running"
else
    echo "   ❌ Vite dev server is NOT running"
    echo "   Start it with: cd apps/client && npm run dev"
    exit 1
fi
echo

# Check backend server
echo "2. Checking NestJS backend (port 3001)..."
if curl -s http://localhost:3001/api/health 2>&1 | grep -q "ok"; then
    echo "   ✅ Backend server is running"
else
    echo "   ❌ Backend server is NOT running or unhealthy"
    echo "   Start it with: pnpm run server:dev"
    exit 1
fi
echo

# Check KB chat service
echo "3. Checking KB Chat service (port 8765)..."
if curl -s http://localhost:8765 > /dev/null 2>&1; then
    echo "   ✅ KB Chat service is running"
else
    echo "   ⚠️  KB Chat service may not be running"
    echo "   Start it with: source scripts/zendesk-poc/venv/bin/activate && python scripts/zendesk-poc/kb_chat_service.py"
fi
echo

echo "======================================================================"
echo "MANUAL TESTING INSTRUCTIONS"
echo "======================================================================"
echo
echo "The frontend is ready for testing!"
echo
echo "Steps:"
echo "  1. Open your browser to: http://localhost:5173"
echo "  2. Login with your Docmost credentials"
echo "  3. Navigate to: http://localhost:5173/kb-chat"
echo "  4. Enter a question (e.g., 'What is zendesk?')"
echo "  5. Click 'Ask Question' and verify:"
echo "     - Answer is displayed"
echo "     - Sources are listed"
echo "     - Clicking a source navigates to the article"
echo
echo "======================================================================"
echo "API ENDPOINT TEST (requires authentication)"
echo "======================================================================"
echo
echo "To test the API directly, you need a valid session cookie."
echo "After logging in via the browser, you can test with:"
echo
echo '  curl -X POST http://localhost:3001/api/kb-chat \'
echo '    -H "Content-Type: application/json" \'
echo '    -H "Cookie: <your-session-cookie>" \'
echo '    -d '"'"'{"question":"What is zendesk?"}'"'"
echo
echo "======================================================================"
