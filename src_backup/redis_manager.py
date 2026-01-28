"""
동적 카메라 정보 업데이트를 위한 Redis 연결 및 구독 관리자.
"""
import redis
import threading
import logging
import time
import json
from typing import Callable, List, Dict


class RedisManager:
    """
    Redis 연결을 관리하고, 초기 카메라 정보를 가져오며, 동적 스트림 관리를 위해
    Pub/Sub을 통해 업데이트를 수신합니다.
    """

    def __init__(self, config, update_callback: Callable[[], None]):
        """
        RedisManager를 초기화합니다.

        Args:
            config: 애플리케이션 설정 객체.
            update_callback: 스트림 목록 업데이트가 감지될 때 호출될 콜백 함수.
        """
        self.logger = logging.getLogger("aegis-agent.redis")
        self.redis_host = getattr(config, 'redis_host', 'localhost')
        self.redis_port = getattr(config, 'redis_port', 6379)
        self.redis_db = getattr(config, 'redis_db', 0)
        self.analysis_cameras_key = getattr(config, 'redis_analysis_cameras_key', 'analysis:cameras')
        self.update_channel = getattr(config, 'redis_update_channel', 'camera:analysis:update')
        self.update_callback = update_callback

        self.redis_client: redis.Redis = None
        self.shutdown_event = threading.Event()
        self.pubsub_thread = threading.Thread(target=self._pubsub_loop, daemon=True)

    def _connect(self):
        """Redis 서버에 연결을 설정합니다."""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            self.redis_client.ping()
            self.logger.info(f"Redis에 성공적으로 연결되었습니다: {self.redis_host}:{self.redis_port}")
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            self.logger.error(f"Redis에 연결할 수 없습니다: {e}. 재시도합니다.")
            self.redis_client = None

    def get_analysis_cameras(self) -> List[Dict]:
        """
        설정된 Redis 키에서 분석 대상 카메라 목록을 가져옵니다.
        값은 [{name, alias}, ...] 형태의 JSON 문자열입니다.

        Returns:
            카메라 정보를 담은 딕셔너리 목록 또는 오류 발생 시 빈 목록.
        """
        if not self.redis_client:
            self.logger.warning("Redis에 연결되지 않았습니다. 카메라 정보를 가져올 수 없습니다.")
            return []
        try:
            cameras_json = self.redis_client.get(self.analysis_cameras_key)
            if not cameras_json:
                self.logger.warning(f"Redis 키 '{self.analysis_cameras_key}'가 비어있거나 존재하지 않습니다.")
                return []

            cameras = json.loads(cameras_json)
            if not isinstance(cameras, list):
                self.logger.error(f"Redis 키 '{self.analysis_cameras_key}'의 데이터가 리스트가 아닙니다.")
                return []

            self.logger.info(f"Redis에서 {len(cameras)}개의 카메라 정보를 가져왔습니다.")
            return cameras
        except json.JSONDecodeError:
            self.logger.error(f"Redis 키 '{self.analysis_cameras_key}'에서 JSON 디코딩에 실패했습니다.")
            return []
        except Exception as e:
            self.logger.error(f"Redis에서 카메라 정보를 가져오는 중 오류 발생: {e}", exc_info=True)
            return []

    def _pubsub_loop(self):
        """
        Pub/Sub 리스너 스레드의 메인 루프입니다.
        업데이트 채널의 메시지를 수신하고 콜백을 트리거합니다.
        """
        while not self.shutdown_event.is_set():
            if not self.redis_client:
                self._connect()
                if not self.redis_client:
                    time.sleep(5)
                    continue

            try:
                pubsub = self.redis_client.pubsub()
                pubsub.subscribe(self.update_channel)
                self.logger.info(f"업데이트를 위해 Redis 채널 '{self.update_channel}'을 구독했습니다.")

                for message in pubsub.listen():
                    if self.shutdown_event.is_set():
                        break
                    if message['type'] == 'message':
                        self.logger.info(
                            f"채널 '{self.update_channel}'에서 업데이트 알림을 수신했습니다. "
                            f"메시지: '{message.get('data')}'"
                        )
                        self.update_callback()

            except redis.exceptions.ConnectionError:
                self.logger.error("Pub/Sub 루프에서 Redis 연결이 끊어졌습니다. 재연결을 시도합니다...")
                self.redis_client = None
                time.sleep(5)
            except Exception as e:
                self.logger.error(f"Redis Pub/Sub 루프에서 예상치 못한 오류 발생: {e}", exc_info=True)
                time.sleep(5)

        self.logger.info("Redis Pub/Sub 리스너가 종료됩니다.")

    def start(self):
        """Pub/Sub 리스너 스레드를 시작합니다."""
        self.logger.info("RedisManager를 시작합니다...")
        self.pubsub_thread.start()

    def shutdown(self):
        """RedisManager를 종료하고 리스너 스레드를 중지합니다."""
        self.logger.info("RedisManager를 종료합니다...")
        self.shutdown_event.set()
        if self.pubsub_thread.is_alive():
            self.pubsub_thread.join(timeout=3)
        if self.redis_client:
            self.redis_client.close()
        self.logger.info("RedisManager가 종료되었습니다.")
