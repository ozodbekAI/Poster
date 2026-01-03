from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.common.config import settings

logger = logging.getLogger(__name__)


class KIEInsufficientCreditsError(Exception):
    def __init__(self, result: dict):
        self.result = result
        msg = result.get("msg") or result.get("message") or "KIE credits are insufficient"
        super().__init__(msg)


class KieClient:
    """KIE official async jobs client.

    Flow:
      1) POST /jobs/createTask -> taskId
      2) GET  /jobs/recordInfo?taskId=... -> state + resultJson
      3) Download resultUrls when success and save into out_dir.
    """

    def __init__(self) -> None:
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY is required")

        # Accept several env names for compatibility.
        base = (
            settings.kie_api_base
            or settings.kie_api_url
            or settings.kie_base_url  # legacy
            or "https://api.kie.ai/api/v1"
        )
        self.base = base.rstrip("/")
        self.create_path = settings.kie_create_path
        self.query_path = settings.kie_query_path
        self.api_key = settings.kie_api_key

        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

    async def upload_base64(self, image_bytes: bytes, filename: str = "input.png") -> str:
        """
        Telegram bytes -> KIE temporary downloadUrl.
        """
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY required")

        upload_url = settings.kie_upload_base64_url  # envdan o'qing
        if not upload_url:
            raise ValueError("KIE_UPLOAD_BASE64_URL required")

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "base64Data": f"data:image/png;base64,{b64}",
            "uploadPath": "images/telegram",
            "fileName": filename,
        }
        headers = {"Authorization": f"Bearer {settings.kie_api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(upload_url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        # sizda KIE response struktura boshqacha bo'lishi mumkin,
        # shuning uchun shu joyni 1 marta log qilib tekshirib moslashtirasiz.
        download_url = (data.get("data") or {}).get("downloadUrl")
        if not download_url:
            raise RuntimeError(f"KIE upload failed: {data}")
        return download_url

    async def close(self) -> None:
        await self.http.aclose()

    async def _create_task(self, *, model: str, input_data: dict) -> str:
        url = f"{self.base}{self.create_path}"
        payload = {"model": model, "input": input_data}
        r = await self.http.post(url, json=payload)
        r.raise_for_status()
        result = r.json()

        code = result.get("code")
        if code == 402:
            raise KIEInsufficientCreditsError(result)
        if code != 200:
            raise ValueError(f"KIE createTask failed: {result.get('msg') or result.get('message') or result}")

        task_id = (result.get("data") or {}).get("taskId")
        if not task_id:
            raise ValueError(f"KIE createTask response missing taskId: {result}")
        return str(task_id)

    async def _get_status(self, *, task_id: str) -> dict:
        url = f"{self.base}{self.query_path}"
        r = await self.http.get(url, params={"taskId": task_id})
        r.raise_for_status()
        result = r.json()
        if result.get("code") != 200:
            raise ValueError(f"KIE recordInfo failed: {result.get('msg') or result.get('message') or result}")

        data = result.get("data") or {}
        state = data.get("state", "unknown")
        result_json_str = data.get("resultJson") or "{}"
        try:
            result_dict = json.loads(result_json_str) if result_json_str else {}
        except Exception:
            result_dict = {}

        if state in {"fail", "failed", "error"}:
            fail_msg = data.get("failMsg") or "Unknown error"
            fail_code = data.get("failCode") or "Unknown"
            raise RuntimeError(f"KIE task failed: {fail_msg} (code: {fail_code})")

        return {"state": state, "result": result_dict}

    async def _poll_task(self, *, task_id: str) -> dict:
        import asyncio

        for attempt in range(int(settings.kie_max_attempts)):
            st = await self._get_status(task_id=task_id)
            state = st["state"]
            if state == "success":
                return st["result"]
            await asyncio.sleep(int(settings.kie_poll_interval_sec))
        raise TimeoutError(
            f"KIE task timeout after {settings.kie_max_attempts} attempts "
            f"({settings.kie_max_attempts * settings.kie_poll_interval_sec} seconds)"
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    async def generate(
        self,
        *,
        prompt: str,
        out_dir: str,
        n: int,
        image_urls: Optional[List[str]] = None,
        output_format: Optional[str] = None,
        image_size: Optional[str] = None,
    ) -> List[str]:
        """Generate n images and save locally.

        If ``image_urls`` is provided, it will be passed to KIE as reference images
        (required for edit models like ``google/nano-banana-edit``).

        Note: Telegram file URLs (``https://api.telegram.org/file/bot<TOKEN>/...``)
        are acceptable as long as KIE can fetch them from the Internet.
        """
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        model = settings.kie_model
        input_data: Dict[str, Any] = {
            "prompt": prompt,
            "output_format": output_format or settings.kie_output_format,
            "image_size": image_size or settings.kie_image_size,
        }

        if image_urls:
            input_data["image_urls"] = image_urls

        # Some KIE models accept "n" directly; for safety we generate one task and take first URL(s),
        # or create multiple tasks. We'll create multiple tasks to guarantee count.
        out_paths: List[str] = []
        for i in range(n):
            task_id = await self._create_task(model=model, input_data=input_data)
            result = await self._poll_task(task_id=task_id)

            urls = result.get("resultUrls") or result.get("result_urls") or []
            if not urls:
                raise ValueError(f"KIE success but no resultUrls: {result}")

            # Take first url
            img_url = urls[0]
            img = await self.http.get(img_url)
            img.raise_for_status()
            fp = Path(out_dir) / f"img_{i+1}.png"
            fp.write_bytes(img.content)
            out_paths.append(str(fp))

        return out_paths
