# app/auth

认证模块与模型路由、缓存和分类逻辑分离，当前只支持 GitHub OAuth 和
Google OAuth。OAuth 身份会绑定到已有用户，已有 Workspace、请求历史、缓存
和 Provider 元数据不会因为切换登录方式而丢失。

## 登录流程

- `GET /api/auth/oauth/github/start`
- `GET /api/auth/oauth/github/callback`
- `GET /api/auth/oauth/google/start`
- `GET /api/auth/oauth/google/callback`
- `GET /api/auth/me`
- `POST /api/auth/logout`

OAuth 回调只接受经过提供商验证的邮箱。首次登录时，如果邮箱已经存在，系统会
将 OAuth 身份关联到原用户；否则创建一个新的用户和 Personal Workspace。

## 配置

生产环境需要在服务端私有环境变量中配置：

```env
AUTH_SECRET_KEY=<random-secret>
GITHUB_OAUTH_CLIENT_ID=<github-client-id>
GITHUB_OAUTH_CLIENT_SECRET=<github-client-secret>
GOOGLE_OAUTH_CLIENT_ID=<google-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-client-secret>
AUTH_FRONTEND_URL=https://<public-origin>
```

GitHub 和 Google 应用的回调地址分别是：

```text
https://<public-origin>/api/auth/oauth/github/callback
https://<public-origin>/api/auth/oauth/google/callback
```

真实 Client Secret 和 `AUTH_SECRET_KEY` 不能提交到 GitHub，也不能返回给前端。

## 数据迁移

迁移版本 004 保留 `users`、Workspace 和业务历史，清除旧密码哈希并删除
`email_verification_tokens`、`password_reset_tokens` 表；新增 `oauth_accounts`
用于保存提供商身份映射。该迁移是幂等的，但会永久移除旧密码登录数据。
