# 04 - Auth

Login and account management for the web UI. Unauthenticated users see the login page; authenticated users interact normally.

## Login Page (`/login`)

Minimal, centered login form. No registration (admin creates accounts).

```mermaid
flowchart TD
    subgraph Login["Login Page"]
        LOGO["Netherbrain"]
        FORM["user_id input<br/>password input<br/>[Sign In] button"]
        ERR["Error message (if any)"]
    end
```

### Behavior

- `POST /api/auth/login` with `{user_id, password}`
- On success: store JWT in `localStorage`, redirect to `/` (chat)
- On error: show inline error message ("Invalid credentials" / "Account deactivated")
- No "forgot password" link (homelab: ask the admin)

### Auth State Management

On app load:

```mermaid
flowchart TD
    LOAD["App loads"] --> TOKEN{"JWT in<br/>localStorage?"}
    TOKEN -->|No| LOGIN["/login"]
    TOKEN -->|Yes| VERIFY["GET /api/auth/me"]
    VERIFY -->|200| CHAT["Enter app"]
    VERIFY -->|401| CLEAR["Clear JWT"]
    CLEAR --> LOGIN
```

- JWT stored as `localStorage.nether_token`
- Attached to all API requests as `Authorization: Bearer {jwt}`
- On 401 from any API call: clear token, redirect to `/login`
- Zustand auth store: `{user, token, isAdmin, login(), logout()}`

## First Login

When admin creates a user, they receive a generated password. The user's first experience:

1. Open web UI -> login page
2. Enter user_id + generated password
3. Redirected to chat (app does not force password change, but user should)
4. Go to Settings -> Account -> change password

## Logout

- Button in sidebar footer (below user display name)
- Clears JWT from localStorage
- Redirects to `/login`

## Role-Aware UI

After login, `GET /api/auth/me` determines what the user sees:

| Element              | Admin | User      |
| -------------------- | ----- | --------- |
| Chat page            | Yes   | Yes       |
| Settings: Presets    | Edit  | Read-only |
| Settings: Workspaces | Edit  | Read-only |
| Settings: Users      | Yes   | No        |
| Settings: Account    | Yes   | Yes       |
| Settings: API Keys   | Yes   | Yes       |
