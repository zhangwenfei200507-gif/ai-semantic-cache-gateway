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
- SQLite 用户数据库

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

## 注意

当前 `forgot-password` 为开发测试版本，会在响应里返回 `dev_reset_token`。

正式部署到 GitHub/公网前，应改为 SMTP/邮件服务发送真正的重置链接，并删除 `dev_reset_token` 返回。
