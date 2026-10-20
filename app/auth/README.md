# app/auth

这是项目的用户认证模块，和现有的模型路由、缓存、Qwen3.8-Flash 分类逻辑分离。

## 包含

- 邮箱 + 密码注册
- 邮箱 + 密码登录
- 当前用户 `/api/auth/me`
- 忘记密码
- 密码重置
- PBKDF2-SHA256 密码哈希
- HMAC-SHA256 Bearer Token
- SQLite 本地开发 / PostgreSQL 生产数据库

这里的“Google邮箱”指可以使用 Gmail 地址注册/登录，并不等于 Google OAuth 登录。

## 接入

在 `app/api/server.py` 增加：

```python
from app.auth import router as auth_router
```

然后在 `create_app()` 中，在 frontend mount 之前增加：

```python
app.include_router(auth_router)
```

## 配置

建议在 `app/config/settings.py` 增加：

```python
auth_secret_key: str | None = None
```

并在 `.env` 设置：

```env
AUTH_SECRET_KEY=换成一串随机长字符串
```

不要把真实 SECRET KEY 提交到 GitHub。

## API

POST `/api/auth/register`

POST `/api/auth/login`

GET `/api/auth/me`，Header：

`Authorization: Bearer <access_token>`

POST `/api/auth/forgot-password`

POST `/api/auth/reset-password`

## 邮件与生产配置

注册验证和密码重置通过邮件服务发送链接；生产环境不会在响应中返回原始
验证 Token 或密码重置 Token。默认本地开发使用 SMTP。若部署平台阻断 SMTP
出站连接，可将 `EMAIL_PROVIDER` 设为 `resend`，并配置
`RESEND_API_KEY` 与已验证的 `RESEND_FROM_EMAIL`，邮件会通过 HTTPS 发送。
通过 `AUTH_FRONTEND_URL` 设置生产链接域名。

生产环境还必须使用 PostgreSQL、启用 CSRF，并配置 `AUTH_SECRET_KEY`。
