"""로그인(2차): 가입·로그인·Google 로그인·토큰 갱신·로그아웃·내 계정·비밀번호 변경·탈퇴·사용자별 설정.

- access token(JWT 15분)은 응답 본문으로 주고, 화면이 Authorization: Bearer 로 보낸다(deps.get_auth_user_id).
- refresh token(14일)은 httpOnly 쿠키(stockmind_refresh, /api/v1/auth 경로에만, SameSite=Strict)로만 오간다.
  POST /auth/refresh가 쓸 때마다 새 토큰으로 바꾼다(app/services/auth.py RefreshStore).
- 가입(이메일·Google 처음)은 이 브라우저의 게스트 행을 계정으로 바꾼다 → 게스트로 담은 관심종목이 그대로 남는다.
다른 기능은 deps.get_current_user_id(로그인했으면 계정, 아니면 게스트/demo)·require_login(로그인 필수)만 쓴다.
"""
from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_auth_user_id, get_db, get_refresh_store, jwt_secret, require_login
from app.core.config import get_settings
from app.core.errors import ServiceUnavailable, Unauthorized
from app.schemas.api import (AuthConfigOut, GoogleLoginIn, LoginIn, MeOut, PasswordChangeIn, PrefsIn, PrefsOut, SignupIn,
                             TokenOut, WithdrawIn)
from app.services import auth as svc
from app.services.auth import RefreshStore

router = APIRouter(prefix="/auth", tags=["auth"], responses={401: {"description": "로그인 필요·토큰 만료·비밀번호 불일치"},
                                                          429: {"description": "로그인 시도 제한"}})
REFRESH_COOKIE, REFRESH_PATH = "stockmind_refresh", "/api/v1/auth"
GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"


def client_ip(request: Request) -> str | None:
    """시도 제한용 클라이언트 IP. Cloud Run은 실제 IP를 X-Forwarded-For 끝에 붙이므로 마지막 값을 쓴다."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()[:45] or None
    return request.client.host if request.client else None


@lru_cache
def _google_jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GOOGLE_CERTS, cache_keys=True)


def get_google_key_resolver():
    """ID token → Google 공개키. 테스트는 이 의존성을 바꿔 가짜 키를 쓴다."""
    return lambda token: _google_jwks().get_signing_key_from_jwt(token).key


def _me(db: Session, user_id: int | None) -> dict:
    acc = svc.account(db, user_id) if user_id is not None else None
    if acc is None:
        return {"logged_in": False, "user_id": None, "nickname": None, "email": None}
    return {"logged_in": True, **acc}


def _tokens(response: Response, db: Session, user_id: int, refresh_token: str) -> dict:
    st = get_settings()
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=st.refresh_token_days * 86400, path=REFRESH_PATH,
                        httponly=True, secure=True, samesite="strict")
    return {"access_token": svc.issue_access_token(user_id, jwt_secret(), st.access_token_minutes),
            "expires_in": st.access_token_minutes * 60, "user": _me(db, user_id)}


def _drop_refresh(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, httponly=True, secure=True, samesite="strict")


def _refresh_failed(e: Unauthorized) -> JSONResponse:
    """401 응답에 쿠키 지우기를 싣는다(예외로 던지면 Response 인자에 단 쿠키가 버려진다)."""
    resp = JSONResponse({"error": {"code": e.code, "message": e.message, "detail": None}}, status_code=401)
    _drop_refresh(resp)
    return resp


def _guest_user_id(request: Request) -> int | None:
    uid = request.session.get("user_id")
    return uid if isinstance(uid, int) else None


def _became_account(request: Request) -> None:
    """게스트 행이 계정이 됐으니 게스트 쿠키 칸을 지운다(로그아웃하면 새 게스트로 시작)."""
    request.session.pop("user_id", None)
    request.session.pop("seen", None)


@router.get("/config", response_model=AuthConfigOut, summary="로그인 화면 설정 (Google 클라이언트 ID)")
def config():
    return {"google_client_id": get_settings().google_client_id or None}


@router.get("/me", response_model=MeOut, summary="내 계정 (토큰 없이 부르면 logged_in=false)")
def me(user_id: int | None = Depends(get_auth_user_id), db: Session = Depends(get_db)):
    return _me(db, user_id)


@router.post("/signup", response_model=TokenOut, status_code=201, summary="가입 (이 브라우저의 게스트 관심종목을 이어 쓴다)")
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db),
           store: RefreshStore = Depends(get_refresh_store)):
    uid = svc.signup(db, body.email, body.password, body.nickname, _guest_user_id(request))
    _became_account(request)
    return _tokens(response, db, uid, store.issue(uid))


@router.post("/login", response_model=TokenOut, summary="로그인 (이메일·비밀번호)")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db),
          store: RefreshStore = Depends(get_refresh_store)):
    uid = svc.login(db, store, body.email, body.password, client_ip(request))
    return _tokens(response, db, uid, store.issue(uid))


@router.post("/google", response_model=TokenOut, summary="Google 로그인 (처음이면 가입)")
def google(body: GoogleLoginIn, request: Request, response: Response, db: Session = Depends(get_db),
           store: RefreshStore = Depends(get_refresh_store), key_resolver=Depends(get_google_key_resolver)):
    client_id = get_settings().google_client_id
    if not client_id:
        raise ServiceUnavailable("Google 로그인이 설정되지 않았어요", code="GOOGLE_LOGIN_DISABLED")
    claims = svc.verify_google_credential(body.credential, client_id, key_resolver)
    uid = svc.google_login(db, claims, _guest_user_id(request))
    if _guest_user_id(request) == uid:
        _became_account(request)
    return _tokens(response, db, uid, store.issue(uid))


@router.post("/refresh", response_model=TokenOut, summary="access token 다시 받기 (refresh token 교체)")
def refresh(request: Request, response: Response, db: Session = Depends(get_db),
            store: RefreshStore = Depends(get_refresh_store)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("로그인이 필요해요", code="REFRESH_INVALID")
    try:
        uid, new = store.rotate(token)
    except Unauthorized as e:
        if e.code == "REFRESH_RETRY":          # 다른 탭이 방금 바꿨다 → 쿠키는 그대로 두고 화면이 다시 시도
            raise
        return _refresh_failed(e)
    if svc.account(db, uid) is None:          # 탈퇴한 계정
        store.revoke(new)
        return _refresh_failed(Unauthorized("다시 로그인해 주세요", code="REFRESH_INVALID"))
    return _tokens(response, db, uid, new)


@router.post("/logout", status_code=204, summary="로그아웃 (이 기기)")
def logout(request: Request, store: RefreshStore = Depends(get_refresh_store)):
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        store.revoke(token)
    response = Response(status_code=204)
    _drop_refresh(response)
    return response


@router.post("/logout-all", status_code=204, summary="모든 기기에서 로그아웃")
def logout_all(user_id: int = Depends(require_login), store: RefreshStore = Depends(get_refresh_store)):
    store.revoke_user(user_id)
    response = Response(status_code=204)
    _drop_refresh(response)
    return response


@router.put("/password", status_code=204, summary="비밀번호 변경·설정 (다른 기기는 로그아웃)")
def change_password(body: PasswordChangeIn, request: Request, user_id: int = Depends(require_login),
                    db: Session = Depends(get_db), store: RefreshStore = Depends(get_refresh_store)):
    svc.change_password(db, user_id, body.current_password, body.new_password)
    store.revoke_user(user_id, keep_token=request.cookies.get(REFRESH_COOKIE))
    return Response(status_code=204)


@router.delete("/me", status_code=204, summary="탈퇴 (관심종목·포트폴리오·설정까지 모두 삭제)")
def withdraw(body: WithdrawIn, user_id: int = Depends(require_login), db: Session = Depends(get_db),
             store: RefreshStore = Depends(get_refresh_store)):
    svc.withdraw(db, user_id, body.password)
    store.revoke_user(user_id)
    response = Response(status_code=204)
    _drop_refresh(response)
    return response


@router.get("/me/preferences", response_model=PrefsOut, summary="내 설정 (테마·투자 성향·지표 선택 등)")
def get_preferences(user_id: int = Depends(require_login), db: Session = Depends(get_db)):
    return svc.get_prefs(db, user_id)


@router.put("/me/preferences", response_model=PrefsOut, summary="내 설정 저장 (보낸 칸만, null은 지움)")
def put_preferences(body: PrefsIn, user_id: int = Depends(require_login), db: Session = Depends(get_db)):
    return svc.save_prefs(db, user_id, body.model_dump(exclude_unset=True))
