import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from mimi_douyin import perception


def test_meaning_survives_validation_and_format():
    value = perception.VideoTranscript.model_validate({"summary": "合成画面", "meaning": "依据字幕的解释候选"}).model_dump()
    assert value["meaning"] == "依据字幕的解释候选"
    assert "含义解释候选（须结合证据）：依据字幕的解释候选" in perception.format_transcript(value)


def test_old_payload_remains_compatible():
    value = perception.VideoTranscript.model_validate({"summary": "旧格式"}).model_dump()
    assert value["meaning"] == ""
    assert "含义解释候选" not in perception.format_transcript(value)


def test_meaning_length_boundary():
    assert len(perception.VideoTranscript(summary="x", meaning="m" * 2400).meaning) == 2400
    with pytest.raises(ValueError):
        perception.VideoTranscript(summary="x", meaning="m" * 2401)


def test_image_request_response_and_cache(tmp_path):
    image = tmp_path / "synthetic.png"
    Image.new("RGB", (2, 2), (20, 40, 60)).save(image)
    rows = {}
    generate = AsyncMock(return_value=NS(role="assistant", completion_text=json.dumps({"summary": "合成图像", "meaning": "依据画面的解释候选"})))
    owner = NS(config={"video_provider_id": "synthetic", "video_separate_audio": False}, media_dir=str(tmp_path),
               video_transcription_lock=asyncio.Lock(), ledger=NS(get=rows.get, put=lambda key,value: rows.update({key:value})),
               context=NS(get_provider_by_id=lambda _: NS(get_model=lambda: "synthetic"), llm_generate=generate))
    async def run():
        first = await perception.transcribe_video(owner, [{"images": [str(image)]}])
        second = await perception.transcribe_video(owner, [{"images": [str(image)]}])
        assert first["meaning"] == "依据画面的解释候选"
        assert "含义解释候选（须结合证据）" in perception.format_transcript(first)
        assert second["cache_hit"] is True
    asyncio.run(run())
    assert generate.await_count == 1
    text = " ".join(part.text for message in generate.call_args.kwargs["contexts"] for part in message.content if part.type == "text")
    assert '"meaning"' in text
    assert all(key.startswith("video-transcript:v3:") for key in rows)
