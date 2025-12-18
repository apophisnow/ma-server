# Music Assistant RBAC Development & Testing Guide

This guide covers running Music Assistant for development and testing the RBAC changes.

## Prerequisites

- Docker and Docker Compose (for containerized setup)
- Python 3.12+ (for local server development)
- Node.js 20+ (for local frontend development)

## Quick Start Options

### Option 1: Both Server and Frontend in Docker (Recommended for Testing)

This runs both server and frontend in containers with live code mounting.

```bash
# From the ma-server directory
docker-compose -f docker-compose.dev.yml up --build

# Access:
# - Server: http://localhost:8095
# - Frontend: http://localhost:5173
```

**Pros:**
- Everything containerized
- Consistent environment
- Easy to start/stop

**Cons:**
- Slower file watching on some systems
- Requires rebuilding for dependency changes

---

### Option 2: Server Local + Frontend in Docker (Best for Server Development)

Run the server locally in debug mode and containerize only the frontend.

#### Step 1: Run Server Locally

```bash
# From ma-server directory
cd /Users/karl/repos/musicassistant/ma-server

# Activate virtual environment (if not already)
source .venv/bin/activate

# Run server
python -m music_assistant --log-level debug

# Or use VS Code debugger (F5) with the provided launch config
```

#### Step 2: Run Frontend in Docker

```bash
# From ma-server directory
docker-compose -f docker-compose.local.yml up

# Access:
# - Server: http://localhost:8095 (local)
# - Frontend: http://localhost:5173 (Docker)
```

**Pros:**
- Fast server restarts
- Easy debugging in VS Code
- Full breakpoint support
- Frontend still containerized for consistency

**Cons:**
- Need to manage server separately

---

### Option 3: Both Local (Maximum Control)

Run both server and frontend locally without Docker.

#### Server

```bash
cd /Users/karl/repos/musicassistant/ma-server
source .venv/bin/activate
python -m music_assistant --log-level debug
```

#### Frontend

```bash
cd /Users/karl/repos/musicassistant/ma-frontend
npm install
npm run dev

# Access: http://localhost:5173
```

**Pros:**
- Fastest development cycle
- Full control and debugging
- No Docker overhead

**Cons:**
- Manual dependency management
- Environment differences

---

## Testing RBAC Changes

### 1. Initial Setup

1. Start server and frontend (using any option above)
2. Navigate to `http://localhost:5173`
3. Complete first-time setup to create admin user

### 2. Test Role Management

1. **Access Roles Page:**
   - Navigate to Settings → Roles
   - Or directly: `http://localhost:5173/settings/roles`

2. **View Default Roles:**
   - Should see 4 system roles: admin, user, guest, dj
   - System roles cannot be edited/deleted (buttons hidden)

3. **Create Custom Role:**
   - Click "Create" button
   - Enter role name and description
   - Use quick permission buttons or type permissions manually
   - Save and verify role appears in list

4. **Edit Custom Role:**
   - Click edit icon on custom role
   - Modify permissions
   - Save and verify changes

5. **Delete Custom Role:**
   - Click delete icon
   - Confirm deletion
   - System roles should not be deletable

### 3. Test Permission Checking (Frontend)

In browser console:

```javascript
// Import auth manager
import { authManager } from '@/plugins/auth'

// Check if user has permission
authManager.hasPermission('player.control')  // true/false
authManager.hasPermission('library.write')   // true/false

// Check multiple permissions
authManager.hasAnyPermission(['player.control', 'library.write'])
authManager.hasAllPermissions(['player.control', 'library.write'])

// View user's roles
authManager.getUserRoles()
```

### 4. Test API Endpoints

Using curl or browser DevTools:

```bash
# Get all roles
curl http://localhost:8095/api/rbac/roles \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get current user's roles
curl http://localhost:8095/api/rbac/user/roles \
  -H "Authorization: Bearer YOUR_TOKEN"

# Create custom role (admin only)
curl -X POST http://localhost:8095/api/rbac/role/create \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DJ Plus",
    "description": "DJ with playlist creation",
    "permissions": ["player.control", "player.volume", "player.queue", "playlist.write"]
  }'

# Get all permissions
curl http://localhost:8095/api/rbac/permissions \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 5. Test Permission Enforcement

1. **Create Test User:**
   - Settings → User Management
   - Create user with limited role (e.g., "guest")

2. **Login as Test User:**
   - Logout from admin
   - Login as test user

3. **Verify Restrictions:**
   - Try accessing admin-only features
   - Should see permission errors
   - UI elements should be hidden based on permissions

---

## Database Location

- **Docker:** `/data/auth.db` (in container, persisted in Docker volume)
- **Local:** `{data_dir}/auth.db` (default: `~/.musicassistant/auth.db`)

### View Database

```bash
# Local
sqlite3 ~/.musicassistant/auth.db

# Docker
docker exec -it music-assistant-server-dev sqlite3 /data/auth.db
```

### Useful SQL Queries

```sql
-- View all roles
SELECT * FROM rbac_roles;

-- View role assignments
SELECT * FROM rbac_user_roles;

-- View users
SELECT user_id, username, role FROM users;

-- View specific user's roles
SELECT r.* FROM rbac_roles r
JOIN rbac_user_roles ur ON r.role_id = ur.role_id
WHERE ur.user_id = 'USER_ID_HERE';
```

---

## Troubleshooting

### Frontend can't connect to server

**Check:**
1. Server is running: `curl http://localhost:8095/api/info`
2. CORS is enabled (should be automatic in dev mode)
3. Frontend is pointing to correct URL (check `VITE_API_URL`)

### Permission errors

**Check:**
1. User has proper role assigned: Query `rbac_user_roles` table
2. Role has required permissions: Check role in Roles UI
3. Legacy role mapping working: Check server logs for RBAC initialization

### Frontend build errors

**Clear and reinstall:**
```bash
cd /Users/karl/repos/musicassistant/ma-frontend
rm -rf node_modules
rm -rf .vite
npm install
```

### Docker volume issues

**Reset volumes:**
```bash
docker-compose -f docker-compose.dev.yml down -v
docker-compose -f docker-compose.dev.yml up --build
```

---

## Development Workflow

### Making Changes

1. **Server Changes:**
   - Edit files in `music_assistant/`
   - Server auto-reloads in debug mode
   - Check logs for errors

2. **Frontend Changes:**
   - Edit files in `ma-frontend/src/`
   - Vite hot-reloads automatically
   - Check browser console for errors

3. **Models Changes:**
   - Edit `models/music_assistant_models/`
   - Reinstall in server venv: `pip install -e ../models`
   - Restart server

### Running Tests

**Server:**
```bash
cd ma-server
source .venv/bin/activate
pytest
pre-commit run --all-files
```

**Frontend:**
```bash
cd ma-frontend
npm run lint
npm run test
```

**Models:**
```bash
cd models
source .venv/bin/activate
pre-commit run --all-files
```

---

## Cleanup

### Stop Docker Compose

```bash
# Stop containers
docker-compose -f docker-compose.dev.yml down

# Stop and remove volumes (fresh start)
docker-compose -f docker-compose.dev.yml down -v
```

### Clean Local Environment

```bash
# Server
rm -rf ~/.musicassistant

# Frontend
cd ma-frontend
rm -rf node_modules .vite dist
```
