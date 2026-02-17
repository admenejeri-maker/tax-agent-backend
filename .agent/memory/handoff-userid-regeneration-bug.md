# 🔧 Handoff: User ID Regeneration Bug Investigation

**Date:** 2026-02-03
**Priority:** HIGH
**Status:** ANALYSIS_PENDING
**Orchestrator:** Antigravity

---

## 📋 Executive Summary

History is "lost" after page refresh despite backend save working correctly. Root cause hypothesis: **`user_id` regenerates on every refresh** instead of persisting in LocalStorage.

---

## 🎯 Problem Statement

### User Report
> "ისტორია იშლება refresh-ის შემდეგ"

### Observed Behavior
1. User sends message → Backend logs "save SUCCESS"
2. User refreshes page → History appears empty
3. Backend MongoDB check shows **different `user_id`** than expected

### Expected Behavior
- `user_id` should persist across refreshes
- History should load for the persisted `user_id`

---

## 📊 Evidence Already Collected (Orchestrator Phase)

### ✅ Backend Save Works
```bash
# Test command executed:
curl -X POST "http://localhost:8080/chat/stream" \
  -d '{"user_id": "debug_test_xyz789", "message": "test", "save_history": true}'

# MongoDB Result: FOUND in scoop_db.conversations ✅
```

### ✅ Other Widget Users Exist in MongoDB
| user_id | updated_at | status |
|---------|------------|--------|
| widget_0kgscj5cxc1 | 19:51 today | ✅ saved |
| widget_0g90t4wqyy | 19:37 today | ✅ saved |
| widget_dp9lp101l3n | 19:32 today | ✅ saved |

### ❌ Reported User IDs Missing
- `widget_8798eb9g6kh` - NOT FOUND
- `widget_pqi665637b` - NOT FOUND

### 🔴 Browser Console Finding
```
[DEBUG SESSION] {
  action: sendMessageStream, 
  convId: ovsbjynggh8, 
  backendSessionId: undefined,    // ← THIS IS SUSPICIOUS
  sessionIdToUse: ovsbjynggh8
}
```

---

## 🔬 Your Mission (Worker Agent)

### Phase 1: Deep Analysis
**Ignore code implementation. Act as System Analyst.**

1. **Investigate `useChatSession.ts`:**
   - How is `user_id` generated?
   - Where is it stored (localStorage key name)?
   - Is there logic that accidentally regenerates it?

2. **Check LocalStorage Persistence:**
   - Is `scoop_user_id` being read/written correctly?
   - Are there any `localStorage.clear()` or removal calls?

3. **Trace the Refresh Flow:**
   - What happens on component mount?
   - Is there a race condition between read and generate?

4. **Identify Hidden Dependencies:**
   - Does consent status affect user_id?
   - Are there multiple places generating user_id?

### Phase 2: Evidence Collection

Collect **concrete evidence** for each finding:
- File paths with line numbers
- Code snippets showing the issue
- Browser test results if needed

### Phase 3: Hypothesis Validation

You must reach **90%+ confidence** before proceeding. Answer these:

1. ☐ Is `user_id` being regenerated on refresh? Where exactly?
2. ☐ Is localStorage being read before write, or write-first?
3. ☐ Are there multiple generation points that conflict?
4. ☐ Does the consent flow interfere with user_id persistence?

### Phase 4: Implementation Plan

Only after 90%+ confidence, create:
1. **Implementation Blueprint** with specific file changes
2. **Test Strategy** to verify the fix:
   - Manual browser test steps
   - Console verification commands
   - MongoDB query to confirm persistence

---

## 📁 Key Files to Investigate

```
frontend/src/hooks/useChatSession.ts  ← PRIMARY SUSPECT
frontend/src/components/Chat.tsx
frontend/src/App.tsx (if user_id is generated there)
```

### LocalStorage Keys to Check
- `scoop_user_id`
- `scoop_history_consent`
- `scoop_session_id`

---

## ⚠️ Constraints

1. **DO NOT implement until approved**
2. **Output Feasibility Report first**
3. **Wait for Orchestrator command to proceed**

---

## 📤 Expected Output Format

```markdown
## Feasibility Report

### Root Cause (Confidence: XX%)
[Your finding here]

### Evidence
1. [File:Line] - [What it shows]
2. [File:Line] - [What it shows]

### Proposed Fix
[High-level approach]

### Test Plan
1. [Step 1]
2. [Step 2]

### Ready for Implementation: YES/NO
```

---

## 🚦 Current Phase: AWAITING WORKER ANALYSIS

**Worker Command:** 
> "Ignore code for now. Act as a System Analyst. Investigate `useChatSession.ts` and related files to find where and why `user_id` is being regenerated on page refresh. Collect evidence with file paths and line numbers. Output a Feasibility Report with 90%+ confidence before proposing any implementation."
