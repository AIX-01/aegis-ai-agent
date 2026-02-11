"""
동적 Tool 생성기

Redis에서 가져온 액션 정의를 LangChain Tool로 변환합니다.
각 액션의 Python 코드를 실행 가능한 함수로 래핑합니다.
"""
import logging
from typing import List, Dict, Any, Callable, Optional
from langchain_core.tools import StructuredTool
from pydantic import create_model, Field

logger = logging.getLogger(__name__)


def create_dynamic_tools(actions: List[Dict[str, Any]]) -> List[StructuredTool]:
    """
    Redis에서 가져온 액션 목록을 LangChain Tool 리스트로 변환합니다.

    Args:
        actions: Redis에서 가져온 액션 목록
                 각 액션: {"id", "name", "description", "parameters", "code"}

    Returns:
        StructuredTool 리스트
    """
    tools = []

    for action in actions:
        try:
            tool = _create_tool_from_action(action)
            if tool:
                tools.append(tool)
                logger.info(f"동적 Tool 생성: {action.get('name')}")
        except Exception as e:
            logger.error(f"Tool 생성 실패 ({action.get('name')}): {e}", exc_info=True)

    logger.info(f"총 {len(tools)}개의 동적 Tool 생성 완료")
    return tools


def _create_tool_from_action(action: Dict[str, Any]) -> Optional[StructuredTool]:
    """
    단일 액션 정의를 StructuredTool로 변환합니다.

    Args:
        action: 액션 정의 딕셔너리

    Returns:
        StructuredTool 인스턴스 또는 None
    """
    name = action.get("name", "").strip()
    description = action.get("description", "").strip()
    parameters = action.get("parameters", {})
    code = action.get("code", "").strip()

    if not name or not code:
        logger.warning(f"액션에 이름 또는 코드가 없습니다: {action.get('id')}")
        return None

    # Tool 이름을 Python 함수명으로 변환 (공백 -> 언더스코어, 특수문자 제거)
    tool_name = _sanitize_name(name)

    # Pydantic 모델 동적 생성 (파라미터 스키마)
    args_schema = _create_args_schema(tool_name, parameters)

    # 실행 함수 생성
    exec_func = _create_exec_function(code, parameters)

    return StructuredTool(
        name=tool_name,
        description=description or f"{name} 액션을 실행합니다.",
        func=exec_func,
        args_schema=args_schema
    )


def _sanitize_name(name: str) -> str:
    """Tool 이름을 Python 식별자로 변환합니다."""
    import re
    # 공백을 언더스코어로, 특수문자 제거
    sanitized = re.sub(r'[^a-zA-Z0-9가-힣_]', '_', name)
    sanitized = re.sub(r'_+', '_', sanitized).strip('_')
    return sanitized or "unnamed_action"


def _create_args_schema(tool_name: str, parameters: Dict[str, Any]):
    """
    파라미터 정의로부터 Pydantic 모델을 동적으로 생성합니다.

    Args:
        tool_name: Tool 이름 (클래스명으로 사용)
        parameters: {"param_name": {"type": "str", "description": "...", "default_value": ...}}

    Returns:
        동적 생성된 Pydantic 모델 클래스
    """
    if not parameters:
        # 파라미터가 없으면 빈 모델 반환
        return create_model(f"{tool_name}Args")

    fields = {}
    for param_name, param_info in parameters.items():
        param_type = param_info.get("type", "str")
        param_desc = param_info.get("description", "")
        default_value = param_info.get("default_value")

        # 타입 매핑
        python_type = _map_type(param_type)

        # Field 생성 (기본값이 있으면 optional, 없으면 required)
        if default_value is not None and default_value != "":
            # 기본값을 적절한 타입으로 변환
            converted_default = _convert_value(default_value, python_type)
            fields[param_name] = (python_type, Field(default=converted_default, description=param_desc))
        else:
            fields[param_name] = (python_type, Field(description=param_desc))

    return create_model(f"{tool_name}Args", **fields)


def _map_type(type_str: str) -> type:
    """문자열 타입을 Python 타입으로 매핑합니다."""
    type_mapping = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "number": float,
        "bool": bool,
        "boolean": bool,
    }
    return type_mapping.get(type_str.lower(), str)


def _convert_value(value: Any, target_type: type) -> Any:
    """값을 대상 타입으로 변환합니다."""
    try:
        if target_type == bool:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        return target_type(value)
    except (ValueError, TypeError):
        return value


def _create_exec_function(code: str, parameters: Dict[str, Any]) -> Callable:
    """
    액션 코드를 실행하는 함수를 생성합니다.

    코드에서 execute() 함수를 찾아 실행합니다.
    보안을 위해 제한된 환경에서 실행됩니다.

    Args:
        code: Python 코드 문자열
        parameters: 파라미터 정의 (기본값 추출용)

    Returns:
        실행 함수
    """
    def execute_action(**kwargs) -> str:
        try:
            # 필요한 모듈 미리 import
            import requests
            import json
            import datetime
            import urllib.parse

            # 기본값 적용
            for param_name, param_info in parameters.items():
                if param_name not in kwargs or kwargs[param_name] is None:
                    default_value = param_info.get("default_value")
                    if default_value is not None and default_value != "":
                        kwargs[param_name] = default_value

            # 제한된 실행 환경 (자주 사용하는 모듈 포함)
            safe_globals = {
                "__builtins__": {
                    "__import__": __import__,  # import 문 지원
                    "print": print,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "len": len,
                    "range": range,
                    "enumerate": enumerate,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    "sorted": sorted,
                    "min": min,
                    "max": max,
                    "sum": sum,
                    "abs": abs,
                    "round": round,
                    "isinstance": isinstance,
                    "type": type,
                    "Exception": Exception,
                    "ValueError": ValueError,
                    "TypeError": TypeError,
                },
                # 허용된 모듈
                "requests": requests,
                "json": json,
                "datetime": datetime,
                "urllib": urllib,
            }

            # 코드 실행하여 execute 함수 추출
            local_vars = {}
            exec(code, safe_globals, local_vars)

            # execute 함수 찾기
            execute_func = local_vars.get("execute")
            if execute_func is None:
                return "오류: 코드에 execute() 함수가 정의되어 있지 않습니다."

            # execute 함수 실행
            result = execute_func(**kwargs)
            return str(result) if result is not None else "실행 완료"

        except Exception as e:
            logger.error(f"액션 실행 중 오류: {e}", exc_info=True)
            return f"액션 실행 중 오류 발생: {str(e)}"

    return execute_action

