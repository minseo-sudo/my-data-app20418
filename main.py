# -*- coding: utf-8 -*-
"""
KOBIS(영화진흥위원회) 일별 박스오피스 조회 스트림릿 앱
- '어제'(한국 시간 기준) 박스오피스를 자동으로 조회해서 보여줍니다.
- 인증키는 코드에 직접 쓰지 않고, 스트림릿 클라우드의 Secrets(비밀 금고)에서 불러옵니다.
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 한국 시간을 정확히 계산하기 위한 표준 라이브러리


# -----------------------------
# 1. 기본 설정
# -----------------------------
API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")


def get_yesterday_kst() -> str:
    """
    한국 시간(KST) 기준으로 '어제' 날짜를 yyyymmdd 형식(8자리 문자열)으로 계산합니다.
    배포 서버의 시계가 한국 시간이 아니어도 항상 정확한 한국 기준 어제 날짜가 나옵니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# -----------------------------
# 2. API 호출 (1시간 동안 결과를 기억함 = 캐시)
# -----------------------------
@st.cache_data(ttl=3600)  # ttl=3600초(1시간) 동안은 같은 날짜로 다시 요청해도 API를 또 부르지 않음
def fetch_box_office(target_dt: str, api_key: str):
    """
    KOBIS API를 호출해서 해당 날짜의 일별 박스오피스 데이터를 가져옵니다.
    성공하면 (True, 영화 리스트) 를 돌려주고,
    실패하면 (False, "사람이 읽을 수 있는 오류 설명") 을 돌려줍니다.
    """
    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 2-1. 네트워크 요청 자체가 실패하는 경우 (인터넷 문제, 타임아웃 등)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, f"KOBIS 서버에 접속하지 못했습니다. 인터넷 연결 상태를 확인해 주세요. (상세: {e})"

    # 2-2. 응답이 200이 아닌 경우 (서버 오류 등)
    if response.status_code != 200:
        return False, f"KOBIS 서버가 오류를 응답했습니다. (상태 코드: {response.status_code})"

    # 2-3. 응답이 JSON 형식이 아닌 경우 (점검 페이지 등이 대신 오는 경우)
    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없습니다. 잠시 후 다시 시도하거나 API 상태를 확인해 주세요."

    # 2-4. 인증키가 틀렸거나 요청 자체에 문제가 있을 때: 상태코드는 200이지만 faultInfo 상자가 옴
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, (
            f"KOBIS API가 오류를 반환했습니다: {message}\n"
            "→ Secrets에 등록한 KOBIS_KEY(인증키)가 정확한지 확인해 주세요."
        )

    # 2-5. 정상 응답이지만 필요한 데이터 구조가 없는 경우
    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return False, "응답에 boxOfficeResult가 없습니다. API 응답 형식이 바뀌었을 수 있습니다."

    movie_list = box_office_result.get("dailyBoxOfficeList")

    # 2-6. 영화 목록이 비어 있는 경우 (예: 아직 집계되지 않은 날짜를 조회한 경우)
    if not movie_list:
        return False, (
            "해당 날짜의 박스오피스 데이터가 비어 있습니다.\n"
            "→ 조회 날짜가 너무 이르거나(아직 집계 전), 날짜 형식(targetDt)을 확인해 주세요."
        )

    return True, movie_list


# -----------------------------
# 3. 문자열 숫자 -> 진짜 숫자로 변환
# -----------------------------
def to_dataframe(movie_list):
    """
    API가 내려주는 값은 전부 문자열이므로, 정렬/그래프에 쓸 수 있도록
    숫자로 바꾼 새 컬럼들을 추가한 데이터프레임을 만듭니다.
    """
    df = pd.DataFrame(movie_list)

    # 숫자로 바꿔야 하는 컬럼들
    numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_cols:
        if col in df.columns:
            # errors="coerce": 혹시 이상한 값이 있어도 앱이 죽지 않고 빈 값(NaN) 처리
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 순위 기준으로 정렬 (혹시 API가 순서를 안 지켜서 줄 수도 있으니 안전하게 한 번 더 정렬)
    df = df.sort_values("rank").reset_index(drop=True)
    return df


# -----------------------------
# 4. 화면 구성
# -----------------------------
def main():
    st.title("🎬 어제의 박스오피스")

    # 4-1. 인증키를 Secrets에서 불러오기 (코드에는 절대 쓰지 않음)
    api_key = st.secrets.get("KOBIS_KEY")
    if not api_key:
        st.error(
            "인증키(KOBIS_KEY)를 찾을 수 없습니다.\n"
            "→ 스트림릿 클라우드 앱 설정의 Secrets에 KOBIS_KEY = \"발급받은키\" 형식으로 등록해 주세요."
        )
        return

    # 4-2. 한국 시간 기준 '어제' 날짜 계산
    target_dt = get_yesterday_kst()
    display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"조회 기준일(한국시간 어제): {display_date}")

    # 4-3. 데이터 가져오기
    success, result = fetch_box_office(target_dt, api_key)

    if not success:
        # 실패 사유를 화면에 친절하게 안내 (빈 화면 대신)
        st.error(result)
        return

    movie_list = result
    df = to_dataframe(movie_list)

    # -----------------------------
    # 4-4. 1위 영화 지표 카드 3장
    # -----------------------------
    top1 = df.iloc[0]
    st.subheader(f"👑 1위: {top1['movieNm']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("어제 관객수", f"{int(top1['audiCnt']):,} 명")
    col2.metric("누적 관객수", f"{int(top1['audiAcc']):,} 명")
    col3.metric("스크린수", f"{int(top1['scrnCnt']):,} 개")

    st.divider()

    # -----------------------------
    # 4-5. 관객수 상위 5편 막대그래프
    # -----------------------------
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    chart_data = top5.set_index("movieNm")["audiCnt"]
    st.bar_chart(chart_data)

    st.divider()

    # -----------------------------
    # 4-6. 전체 표
    # -----------------------------
    st.subheader("📋 전체 순위표")

    table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]

    # 표 안에서도 숫자에 콤마(천 단위 구분)를 넣어서 보기 좋게 표시
    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn(format="%d"),
            "누적관객": st.column_config.NumberColumn(format="%d"),
            "스크린수": st.column_config.NumberColumn(format="%d"),
        },
    )


if __name__ == "__main__":
    main()
