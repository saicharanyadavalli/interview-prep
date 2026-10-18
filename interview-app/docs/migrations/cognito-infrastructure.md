# AWS Cognito and Google OAuth 2.0 Infrastructure Specification

## 1. Executive Summary & Architecture

This document defines the production and personal staging authentication infrastructure, Google OAuth 2.0 federation, Hosted UI configurations, CloudFormation automation, operator deployment runbooks, and rollback procedures for migrating the Interview Prep authentication tier to Amazon Cognito.

### Architecture Overview

```mermaid
flowchart TD
    subgraph Clients["Client Layer"]
        Browser["Next.js Web Client\n(Public Client with PKCE)"]
    end

    subgraph IdentityFederation["External Identity Provider"]
        Google["Google Cloud Console\nOAuth 2.0 Client\nopenid profile email"]
    end

    subgraph AWS_Cognito["AWS ap-south-2 (Hyderabad) - Amazon Cognito"]
        UserPoolDomain["Cognito Hosted UI Domain\ninterview-prep-auth-<account>-<env>.auth.ap-south-2.amazoncognito.com"]
        
        GoogleIdP["UserPoolIdentityProvider (Google)\nAttribute Mapping: email, name, sub"]
        
        UserPoolClient["UserPoolClient (Public PKCE)\nExplicitAuthFlows: USER_PASSWORD_AUTH, USER_SRP_AUTH, REFRESH_TOKEN\nAllowedOAuthFlows: code\nScopes: openid, email, profile\nToken Revocation: Enabled"]
        
        UserPool["Cognito User Pool\nUsernameAttributes: [email]\nAutoVerified: [email]\nPassword Policy & Advanced Security"]
    end

    subgraph BackendAPI["Compute Layer (EC2 / FastAPI)"]
        FastAPI["FastAPI Application\nJWT JWKS Verification\nIssuer: https://cognito-idp.ap-south-2.amazonaws.com/<user-pool-id>"]
        Postgres["Amazon RDS PostgreSQL\nTable: user_profiles (sub -> id)"]
    end

    %% Method 1: Native Email & Password
    Browser -.->|Method 1: Direct Sign-In (USER_PASSWORD_AUTH / SRP)| UserPoolClient
    UserPoolClient -.->|Validate Password & Issue Tokens| UserPool
    UserPool -.->|Return Access, ID, Refresh Tokens| Browser

    %% Method 2: Google OAuth Federation
    Browser -->|Method 2: Initiate OAuth / Hosted UI Login| UserPoolDomain
    UserPoolDomain -->|Redirect to Google Auth| Google
    Google -->|Authorize & Callback to /oauth2/idpresponse| UserPoolDomain
    UserPoolDomain -->|Map Google Claims & Create/Update User| UserPool
    UserPoolDomain -->|Redirect with Authorization Code| Browser
    Browser -->|Exchange Code + PKCE Verifier for Tokens| UserPoolClient

    %% Backend Verification
    Browser ==>|API Request with Bearer AccessToken| FastAPI
    FastAPI ==>|Verify JWT against Cognito JWKS Endpoint| UserPool
    FastAPI ==>|Lookup / Sync User Profile| Postgres
```

### Supported Authentication Methods

The Cognito User Pool Client (`interview-prep-web-client`) supports two complementary authentication mechanisms configured through `ExplicitAuthFlows` and `AllowedOAuthFlows`:

#### 1. Native Email & Password Authentication (USER_PASSWORD_AUTH / SRP)
- **Enabled Flows (`ExplicitAuthFlows`)**:
  - `ALLOW_USER_PASSWORD_AUTH`: Enables direct username (email) and password authentication over HTTPS TLS without requiring Hosted UI redirects. Ideal for standard in-app login forms, headless automation, and integration tests.
  - `ALLOW_USER_SRP_AUTH`: Enables Secure Remote Password (SRP) protocol for zero-knowledge password verification, ensuring password hashes never cross the wire.
  - `ALLOW_REFRESH_TOKEN_AUTH`: Allows the client to silently exchange a valid refresh token (30 days validity) for fresh access and ID tokens (60 minutes validity) via `InitiateAuth`.
- **User Registration & Email Verification**:
  - Sign-up is open (`AllowAdminCreateUserOnly: false`) with `email` as the primary username attribute.
  - New user registrations receive a 6-digit confirmation code via email (`CONFIRM_WITH_CODE`) to verify email address ownership (`AutoVerifiedAttributes: [email]`).
- **Self-Service Password Recovery**:
  - Users can initiate password recovery via `ForgotPassword` and complete the reset using `ConfirmForgotPassword` with an emailed verification code.
- **Enumeration Attack Prevention**:
  - Configured with `PreventUserExistenceErrors: ENABLED` so that failed authentication or password recovery attempts do not disclose whether a user account exists.

#### 2. Google OAuth 2.0 Social Identity Federation
- **Protocol**: OAuth 2.0 Authorization Code Grant with Proof Key for Code Exchange (PKCE, RFC 7636).
- **Client Configuration**: Public web client (`GenerateSecret: false`), `AllowedOAuthFlows: [code]`, `AllowedOAuthFlowsUserPoolClient: true`, `AllowedOAuthScopes: [openid, email, profile]`.
- **Endpoints & Redirection**:
  - Hosted UI / Authorization Endpoint: `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/authorize`
  - Google Cloud Console Redirect URI: `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/idpresponse`
  - Token Exchange Endpoint: `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/token`
- **Federation Workflow**:
  1. The browser initiates login with Google via Hosted UI or direct federation link (`/oauth2/authorize?identity_provider=Google&...`).
  2. Google authenticates the user and posts the authorization response back to Cognito's callback endpoint: `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/idpresponse`.
  3. Cognito retrieves user claims from Google and maps `email`, `name`, and `username: sub` to create or update the user record in the User Pool.
  4. Cognito issues an authorization code and redirects the browser back to the application callback URL (e.g. `https://app.interviewprep.com/auth/callback` or `http://localhost:3000/auth/callback`).
  5. The web client exchanges the authorization code and PKCE `code_verifier` at `/oauth2/token` for Access, ID, and Refresh tokens.

### Key Security & Operational Principles

1. **Authorization Code Grant with PKCE**: The web client uses OAuth 2.0 Authorization Code flow with Proof Key for Code Exchange (PKCE, RFC 7636). No client secret is stored in frontend assets (`GenerateSecret: false`).
2. **Strict Attribute Mapping**: Google's unique subject identifier (`sub`) maps directly to the Cognito username handle, preventing account collision while guaranteeing stable user references across sessions.
3. **Canonical Identity & Verification**: Email is the primary sign-in handle (`UsernameAttributes: [email]`), with automatic verification code delivery (`AutoVerifiedAttributes: [email]`).
4. **Threat Detection & Auditing**: Amazon Cognito Threat Protection / Advanced Security is parameterized (`AdvancedSecurityMode: AUDIT` default) to log credential stuffing and anomalous logins without blocking legitimate users during onboarding.
5. **Session Governance & Token Revocation**: Access and ID tokens remain valid for 60 minutes, while refresh tokens remain valid for 30 days. Token revocation (`EnableTokenRevocation: true`) enables immediate session invalidation upon user logout or incident mitigation.
6. **Zero Accidental Data Loss**: User pool resources enforce `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` so that user identity state is preserved even if the CloudFormation stack is updated or removed.

---

## 2. Resource Specifications & Target Environment

| Parameter | Value | Description |
|---|---|---|
| **AWS Account ID** | `808431466075` | Target AWS deployment account |
| **AWS Region** | `ap-south-2` | Hyderabad, India |
| **Cognito User Pool Name** | `interview-prep-user-pool-${Environment}` | Authoritative user identity store |
| **Cognito Domain Prefix Pattern** | `interview-prep-auth-${AWS::AccountId}-${Environment}` | Hosted UI domain prefix |
| **Cognito Hosted UI URL** | `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com` | Base URL for Hosted UI and OAuth endpoints |
| **Google IdP Response URI** | `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/idpresponse` | Authorized redirect URI for Google OAuth |
| **App Client Name** | `interview-prep-web-client` | Public PKCE client for browser and SPA applications |
| **Explicit Auth Flows** | `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH` | Supported direct API authentication flows |
| **Allowed OAuth Scopes** | `openid`, `email`, `profile` | Standard OpenID Connect claims |
| **Supported Identity Providers** | `COGNITO`, `Google` | Multi-provider authentication matrix |

---

## 3. Step-by-Step Google Cloud Console Setup

Before or during CloudFormation deployment, register an OAuth 2.0 Web Application in Google Cloud Console.

### Step 3.1: Navigate to Google Cloud Console
1. Open the [Google Cloud Console Credentials Page](https://console.cloud.google.com/apis/credentials).
2. Select your Google Cloud Project (or create a project named `Interview Prep`).

### Step 3.2: Configure OAuth Consent Screen (If Not Already Configured)
1. Navigate to **APIs & Services** > **OAuth consent screen**.
2. Select **External** user type and click **Create**.
3. Fill in the required application details:
   - **App name**: `Interview Prep`
   - **User support email**: Your administrative email address.
   - **Developer contact information**: Your administrative email address.
4. Under **Scopes**, ensure the following scopes are added:
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `openid`
5. Save and continue.

### Step 3.3: Create OAuth 2.0 Client ID
1. Navigate to **APIs & Services** > **Credentials**.
2. Click **Create Credentials** > **OAuth client ID**.
3. Set **Application type** to **Web application**.
4. Set **Name** to `Interview Prep Cognito Client`.
5. Under **Authorized JavaScript origins**, add:
   - `https://app.interviewprep.com` (Production canonical domain)
   - `http://localhost:3000` (Local development environment)
   - `https://interview-prep-auth-808431466075-personal.auth.ap-south-2.amazoncognito.com` (Cognito Hosted UI domain)
6. Under **Authorized redirect URIs**, add the exact Cognito IdP response endpoint:
   - **Canonical Pattern**: `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/idpresponse`
   - **Personal Staging Environment**:
     `https://interview-prep-auth-808431466075-personal.auth.ap-south-2.amazoncognito.com/oauth2/idpresponse`
   - **Production Environment**:
     `https://interview-prep-auth-808431466075-production.auth.ap-south-2.amazoncognito.com/oauth2/idpresponse`
   - **Custom Domain Prefix** (if `CognitoDomainPrefix` parameter is configured):
     `https://<custom-prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse`
7. Click **Create**.
8. Copy the generated **Client ID** (e.g. `1234567890-abcdef.apps.googleusercontent.com`) and **Client Secret**.

> [!IMPORTANT]
> The Authorized redirect URI in Google Cloud Console MUST point to Amazon Cognito's `/oauth2/idpresponse` endpoint, NOT to the application callback URL (`/auth/callback`). Google redirects to Cognito to issue federated user identity tokens; Cognito then redirects the user back to the application callback URL with an authorization code.

---

## 4. CloudFormation Deployment Runbook

The template is located at `infrastructure/cloudformation/cognito-auth.yaml`.

### Step 4.1: Syntax and Structure Preflight Check
Validate the CloudFormation template locally before deploying:

```bash
python -c "
import yaml
class CfnYamlLoader(yaml.SafeLoader): pass
for tag in ['!Ref', '!Sub', '!GetAtt', '!If', '!Not', '!Equals', '!And', '!Or', '!Condition']:
    CfnYamlLoader.add_constructor(tag, lambda loader, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node))
with open('infrastructure/cloudformation/cognito-auth.yaml', 'r') as f:
    yaml.load(f, Loader=CfnYamlLoader)
print('CloudFormation YAML syntax verified successfully.')
"
```

### Step 4.2: Deploying Personal / Staging Environment
Set your Google OAuth credentials as environment variables to keep secrets out of bash history:

```bash
export GOOGLE_CLIENT_ID="<your-client-id>.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="<your-client-secret>"
export AWS_REGION="ap-south-2"
export STACK_NAME="interview-prep-cognito-personal"
```

Execute the CloudFormation deployment:

```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/cognito-auth.yaml \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --parameter-overrides \
      Environment=personal \
      GoogleClientId="${GOOGLE_CLIENT_ID}" \
      GoogleClientSecret="${GOOGLE_CLIENT_SECRET}" \
      CanonicalDomain="app.interviewprep.com" \
      CallbackURLs="https://app.interviewprep.com/auth/callback,http://localhost:3000/auth/callback" \
      LogoutURLs="https://app.interviewprep.com/login,http://localhost:3000/login" \
      AdvancedSecurityMode="AUDIT" \
  --no-fail-on-empty-changeset
```

### Step 4.3: Deploying Bootstrap Without Google Credentials (Optional)
If Google credentials are not yet ready and you wish to provision the Cognito User Pool first to obtain the exact domain prefix for Google Cloud Console registration:

```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/cognito-auth.yaml \
  --stack-name interview-prep-cognito-personal \
  --region ap-south-2 \
  --parameter-overrides \
      Environment=personal \
  --no-fail-on-empty-changeset
```

Once Google credentials are created, re-run the command with `GoogleClientId` and `GoogleClientSecret` to activate Google federation.

### Step 4.4: Deploying Production Environment
For production deployment, enforce `Environment=production`, configure strict production callback and logout URLs, and enable `AdvancedSecurityMode=ENFORCED`:

```bash
export GOOGLE_CLIENT_ID="<production-client-id>.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="<production-client-secret>"
export AWS_REGION="ap-south-2"
export STACK_NAME="interview-prep-cognito-production"

aws cloudformation deploy \
  --template-file infrastructure/cloudformation/cognito-auth.yaml \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --parameter-overrides \
      Environment=production \
      GoogleClientId="${GOOGLE_CLIENT_ID}" \
      GoogleClientSecret="${GOOGLE_CLIENT_SECRET}" \
      CanonicalDomain="app.interviewprep.com" \
      CallbackURLs="https://app.interviewprep.com/auth/callback" \
      LogoutURLs="https://app.interviewprep.com/login" \
      AdvancedSecurityMode="ENFORCED" \
  --no-fail-on-empty-changeset
```

---

## 5. CloudFormation Parameters Reference

| Parameter Name | Type | Default | Description |
|---|---|---|---|
| `Environment` | String | `personal` | Deployment stage (`personal` or `production`). |
| `CognitoDomainPrefix` | String | `""` (empty) | Custom Hosted UI domain prefix. If omitted, defaults to `interview-prep-auth-${AWS::AccountId}-${Environment}`. |
| `GoogleClientId` | String | `""` (empty) | Google OAuth 2.0 Web Client ID. If omitted, stack deploys with native email/password auth. |
| `GoogleClientSecret` | String (NoEcho) | `""` (empty) | Google OAuth 2.0 Web Client Secret. Masked in CloudFormation events and console. |
| `CanonicalDomain` | String | `app.interviewprep.com` | Production canonical application domain. |
| `CallbackURLs` | CommaDelimitedList | `https://app.interviewprep.com/auth/callback, http://localhost:3000/auth/callback` | Authorized redirect URIs for OAuth 2.0 Authorization Code flow. |
| `LogoutURLs` | CommaDelimitedList | `https://app.interviewprep.com/login, http://localhost:3000/login` | Authorized redirect URIs for user sign-out. |
| `AdvancedSecurityMode` | String | `AUDIT` | Threat detection mode (`OFF`, `AUDIT`, `ENFORCED`). |
| `AccessTokenValidity` | Number | `60` | Validity duration of Access Tokens in minutes (5 to 1440). |
| `IdTokenValidity` | Number | `60` | Validity duration of ID Tokens in minutes (5 to 1440). |
| `RefreshTokenValidity` | Number | `30` | Validity duration of Refresh Tokens in days (1 to 3650). |

---

## 6. CloudFormation Stack Outputs Reference

| Output Key | Value Format | Description |
|---|---|---|
| `UserPoolId` | `ap-south-2_xxxxxxxxx` | Cognito User Pool ID. Used by backend to verify JWT signatures. |
| `UserPoolArn` | `arn:aws:cognito-idp:ap-south-2:808431466075:userpool/...` | ARN of the User Pool for IAM policy definitions. |
| `UserPoolClientId` | `24-character alphanumeric` | Public App Client ID for Next.js frontend SDK. |
| `CognitoDomain` | `interview-prep-auth-...` | Domain prefix identifier. |
| `UserPoolProviderURL` | `https://cognito-idp.ap-south-2.amazonaws.com/<user-pool-id>` | OIDC discovery issuer URL. |
| `HostedUIDomain` | `https://<domain-prefix>.auth.ap-south-2.amazoncognito.com` | Base URL for Hosted UI login pages. |
| `GoogleOAuthRedirectUri` | `https://<domain-prefix>.auth.ap-south-2.amazoncognito.com/oauth2/idpresponse` | URI to register in Google Cloud Console. |
| `OAuthAuthorizeUrl` | `https://<domain-prefix>.auth.ap-south-2.amazoncognito.com/oauth2/authorize` | Authorization endpoint to initiate code flows. |
| `OAuthTokenUrl` | `https://<domain-prefix>.auth.ap-south-2.amazoncognito.com/oauth2/token` | Token exchange endpoint for PKCE verification. |

### Inspecting Outputs Post-Deployment

```bash
aws cloudformation describe-stacks \
  --stack-name interview-prep-cognito-personal \
  --region ap-south-2 \
  --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
  --output table
```

---

## 7. Application Configuration & Environment Variables

### Frontend Environment Variables (`frontend/.env.production` / `.env.local`)

```env
# AWS Cognito Authentication Configuration
NEXT_PUBLIC_AUTH_PROVIDER=cognito
NEXT_PUBLIC_COGNITO_USER_POOL_ID=ap-south-2_xxxxxxxxx
NEXT_PUBLIC_COGNITO_CLIENT_ID=<UserPoolClientId>
NEXT_PUBLIC_COGNITO_DOMAIN=https://interview-prep-auth-808431466075-personal.auth.ap-south-2.amazoncognito.com
NEXT_PUBLIC_AUTH_REDIRECT_URL=http://localhost:3000/auth/callback
NEXT_PUBLIC_AUTH_LOGOUT_URL=http://localhost:3000/login
```

### Backend Environment Variables (`backend/.env`)

```env
# AWS Cognito JWT Verification
COGNITO_USER_POOL_ID=ap-south-2_xxxxxxxxx
COGNITO_APP_CLIENT_ID=<UserPoolClientId>
COGNITO_REGION=ap-south-2
COGNITO_ISSUER=https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_xxxxxxxxx
```

### Backend FastAPI JWT Verification Architecture

FastAPI verifies incoming JWTs by fetching the public JSON Web Key Set (JWKS) from Cognito's well-known endpoint:

```
https://cognito-idp.ap-south-2.amazonaws.com/<UserPoolId>/.well-known/jwks.json
```

Claims verified on every protected request:
- `iss` matches `https://cognito-idp.ap-south-2.amazonaws.com/<UserPoolId>`
- `aud` (for ID tokens) or `client_id` (for Access tokens) matches `<UserPoolClientId>`
- `token_use` matches `access` or `id`
- `exp` is in the future
- User identity (`sub`) is extracted and used to scope database records in PostgreSQL `user_profiles`.

---

## 8. Rollback and Cleanup Procedures

### Scenario A: Automated Stack Rollback Monitoring
If a stack creation or update fails (e.g. invalid Google credentials, duplicate domain prefix, or quota limits), CloudFormation automatically triggers `ROLLBACK_IN_PROGRESS` or `UPDATE_ROLLBACK_IN_PROGRESS` and returns resources to their last known stable state.

To monitor rollback progress and diagnose the failure root cause:

```bash
aws cloudformation describe-stack-events \
  --stack-name interview-prep-cognito-personal \
  --region ap-south-2 \
  --query "StackEvents[?ResourceStatusReason!=null].[LogicalResourceId,ResourceStatus,ResourceStatusReason]" \
  --output table
```

### Scenario B: Explicit Manual Stack Rollback CLI Command
If a stack update is paused or in a rollback-failed state, or you need to explicitly trigger a rollback via the AWS CLI:

```bash
aws cloudformation rollback-stack \
  --stack-name interview-prep-cognito-personal \
  --region ap-south-2
```

Wait for the rollback to complete:

```bash
aws cloudformation wait stack-rollback-complete \
  --stack-name interview-prep-cognito-personal \
  --region ap-south-2
```

### Scenario C: Reverting to a Previous CloudFormation Template Version
If an update was applied successfully but unintended application behavior requires rolling back to a previous configuration:

1. Restore the previous stable template version from Git:
   ```bash
   git checkout HEAD~1 -- infrastructure/cloudformation/cognito-auth.yaml
   ```

2. Redeploy the previous template configuration:
   ```bash
   aws cloudformation deploy \
     --template-file infrastructure/cloudformation/cognito-auth.yaml \
     --stack-name interview-prep-cognito-personal \
     --region ap-south-2 \
     --parameter-overrides \
         Environment=personal \
         GoogleClientId="${GOOGLE_CLIENT_ID}" \
         GoogleClientSecret="${GOOGLE_CLIENT_SECRET}" \
         CanonicalDomain="app.interviewprep.com" \
         CallbackURLs="https://app.interviewprep.com/auth/callback,http://localhost:3000/auth/callback" \
         LogoutURLs="https://app.interviewprep.com/login,http://localhost:3000/login" \
         AdvancedSecurityMode="AUDIT" \
     --no-fail-on-empty-changeset
   ```

### Scenario D: Decommissioning the Personal / Staging Stack
Because the User Pool specifies `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`, deleting the CloudFormation stack removes the domain, client, and identity provider, while preserving user records in the User Pool.

1. Delete the CloudFormation stack:
   ```bash
   aws cloudformation delete-stack \
     --stack-name interview-prep-cognito-personal \
     --region ap-south-2
   ```

2. Wait for stack deletion to complete:
   ```bash
   aws cloudformation wait stack-delete-complete \
     --stack-name interview-prep-cognito-personal \
     --region ap-south-2
   ```

3. (Optional) If you explicitly want to permanently delete the retained Cognito User Pool:
   ```bash
   USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 10 --region ap-south-2 \
     --query "UserPools[?Name=='interview-prep-user-pool-personal'].Id" --output text)

   if [ -n "$USER_POOL_ID" ]; then
     aws cognito-idp delete-user-pool \
       --user-pool-id "${USER_POOL_ID}" \
       --region ap-south-2
     echo "Deleted retained User Pool: ${USER_POOL_ID}"
   fi
   ```

---

## 9. Verification & Smoke Test Checklist

- [ ] CloudFormation template validates with PyYAML custom loader.
- [ ] User Pool deployed in `ap-south-2` with `UsernameAttributes: [email]`.
- [ ] Password complexity rules require minimum 8 characters, lowercase, uppercase, numbers, and symbols.
- [ ] Schema contains mutable `email`, `name`, and `username` attributes.
- [ ] Hosted UI domain prefix `interview-prep-auth-...` active and reachable over HTTPS.
- [ ] Google OAuth 2.0 Web Client credentials created in Google Cloud Console.
- [ ] Authorized redirect URI set to `https://${CognitoDomain}.auth.${AWS::Region}.amazoncognito.com/oauth2/idpresponse`.
- [ ] Google Identity Provider resource configured in User Pool with attribute mapping (`email`, `name`, `username: sub`).
- [ ] App Client configured as public client with PKCE (`GenerateSecret: false`, `AllowedOAuthFlows: [code]`).
- [ ] Explicit authentication flows configured: `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`.
- [ ] Threat prevention enabled: `PreventUserExistenceErrors: ENABLED`.
- [ ] Token validity configured to 60m (Access/ID) and 30d (Refresh) with token revocation enabled (`EnableTokenRevocation: true`).
- [ ] Stack outputs exported with `${AWS::StackName}-<OutputName>` naming convention.
