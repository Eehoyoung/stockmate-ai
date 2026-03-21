# 키움 API – 토큰 인증

## au10001 접근토큰 발급

**URL**: `POST https://api.kiwoom.com/oauth2/token`  
**모의**: `POST https://mockapi.kiwoom.com/oauth2/token`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `grant_type` | String | Y | `"client_credentials"` 고정 |
| `appkey` | String | Y | 앱키 |
| `secretkey` | String | Y | 시크릿키 |

### Response Body
| 필드 | 설명 |
|------|------|
| `token` | 액세스 토큰 |
| `token_type` | `"bearer"` |
| `expires_dt` | 만료일시 (YYYYMMDDHHmmss) |
| `return_code` | 0=정상 |

### 예시
```json
// Request
{"grant_type":"client_credentials","appkey":"AxserEsdcredca...","secretkey":"SEefdcwcforehDre2fdvc..."}

// Response
{"expires_dt":"20241107083713","token_type":"bearer","token":"WQJCwyqInphKnR3bSRtB9NE1lv...","return_code":0,"return_msg":"정상적으로 처리되었습니다"}
```

### 주의
- Redis 키: `kiwoom:access_token`, TTL: `(만료시간 - 15분)`
- 모든 API 호출 시 Header: `authorization: Bearer {token}`
- `return_code` 필드명 주의: 응답 예시에서 `token` (not `access_token`)

---

## au10002 접근토큰 폐기

**URL**: `POST https://api.kiwoom.com/oauth2/revoke`

### Request Body
| 필드 | 필수 | 설명 |
|------|------|------|
| `appkey` | Y | 앱키 |
| `secretkey` | Y | 시크릿키 |
| `token` | Y | 폐기할 토큰 |
