"""
base_pattern.py — 패턴 추상 기반 클래스
새 패턴을 만들 때 이 클래스를 상속하여 detect() 메서드만 구현하면 됩니다.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class BasePattern(ABC):
    """
    패턴 추상 기반 클래스.

    서브클래스는 반드시 다음을 정의해야 합니다:
    - name (str): 패턴 고유 이름 (파일명에도 사용)
    - description (str): 한국어 패턴 설명
    - default_params (dict): 기본 파라미터

    그리고 detect() 메서드를 구현해야 합니다.
    """

    # 서브클래스에서 반드시 오버라이드
    name: str = "unnamed_pattern"
    description: str = ""
    default_params: dict = {}

    def __init__(self, params: dict = None):
        """
        Parameters
        ----------
        params : dict, optional
            패턴 파라미터. None이면 default_params 사용.
        """
        self.params = {**self.default_params, **(params or {})}
        self.created_at = datetime.today().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # 핵심 메서드 — 서브클래스 구현 필수
    # ------------------------------------------------------------------

    @abstractmethod
    def detect(self, df: pd.DataFrame, **kwargs) -> list[datetime]:
        """
        단일 종목 OHLCV DataFrame에서 신호일 목록 반환.

        Parameters
        ----------
        df : pd.DataFrame
            단일 종목 데이터.
            columns: date(datetime), open, high, low, close, volume
            날짜 오름차순 정렬 보장.
        **kwargs
            런타임 오버라이드 파라미터

        Returns
        -------
        list[datetime]
            신호가 발생한 날짜 목록 (없으면 빈 리스트)
        """
        ...

    # ------------------------------------------------------------------
    # JSON 직렬화 / 역직렬화
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """패턴 정의를 딕셔너리로 직렬화"""
        return {
            "name": self.name,
            "created_at": self.created_at,
            "description_ko": self.description,
            "module": self.__class__.__module__,
            "class": self.__class__.__name__,
            "params": self.params,
            "forward_days": self.params.get("forward_days", 5),
            "last_run": None,
            "last_result_summary": None,
        }

    def save(self, patterns_dir: Path = None) -> Path:
        """
        패턴을 JSON 파일로 저장.

        Parameters
        ----------
        patterns_dir : Path, optional
            저장 디렉토리. 기본값: 프로젝트 루트의 patterns/

        Returns
        -------
        Path
            저장된 파일 경로
        """
        if patterns_dir is None:
            patterns_dir = Path(__file__).parent.parent.parent / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        file_path = patterns_dir / f"{self.name}.json"
        data = self.to_dict()

        # 기존 파일이 있으면 last_run, last_result_summary 유지
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            data["last_run"] = existing.get("last_run")
            data["last_result_summary"] = existing.get("last_result_summary")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return file_path

    def update_last_run(self, summary: dict, patterns_dir: Path = None):
        """백테스트 완료 후 마지막 실행 정보 갱신"""
        if patterns_dir is None:
            patterns_dir = Path(__file__).parent.parent.parent / "patterns"
        file_path = patterns_dir / f"{self.name}.json"

        if not file_path.exists():
            self.save(patterns_dir)

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        data["last_run"] = datetime.today().strftime("%Y-%m-%d %H:%M")
        data["last_result_summary"] = summary

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_json(cls, file_path: Path) -> dict:
        """JSON 파일에서 패턴 메타데이터 로드 (클래스 복원 아님)"""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
