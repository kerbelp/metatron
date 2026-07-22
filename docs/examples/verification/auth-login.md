---
type: Metatron Verification
scope: services/auth
confidence: high
source_refs:
  - services/auth/login.py
runner: docker-compose        # advisory: which runner this contract assumes
---

## Assumptions
Pre-existing state verified before setup runs:
- PostgreSQL reachable on `localhost:5432`, Redis on `localhost:6379`
- Env var `JWT_SECRET` is set

## Setup
    npm run db:migrate
    npm run db:seed -- --fixture=auth_users

## Checks
### Successful login returns a bearer token  [tags: smoke, critical-path]
Action:
    curl -s -X POST localhost:3000/api/v1/auth/login \
      -d '{"email":"user@example.com","password":"Correct123!"}'
Expect:
- exit 0
- stdout jsonpath $.tokenType == Bearer
- stdout jsonpath $.accessToken exists

### Wrong password is rejected, not accepted  [tags: security, regression]
Action:
    curl -s -X POST localhost:3000/api/v1/auth/login \
      -d '{"email":"user@example.com","password":"wrong"}'
Expect:
- exit 0
- stdout jsonpath $.error.code == INVALID_CREDENTIALS

## Failure Means
- happy path missing `accessToken` -> seed hash mismatch or missing user;
  `JWT_SECRET` unset.
- wrong-password check returning a token -> auth middleware is not rejecting bad
  credentials; treat as a security regression, release-blocking.
- `curl` exit != 0 -> gateway/port 3000 down; setup did not complete.

## Teardown
    npm run db:clean
