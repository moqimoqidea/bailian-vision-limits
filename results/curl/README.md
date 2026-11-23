# 失败用例复现脚本

每个用例都有两份：

- `*.sh`：用 curl 重放（macOS / Linux）
- `*.cmd`：Windows 双击或命令行执行，内部调用 `python run_tests.py --replay`

先设置环境变量：

```bash
export DASHSCOPE_API_KEY='sk-...'
export DASHSCOPE_WORKSPACE_ID='ws-...'
bash text_en_openai_ladder_4_4.sh
bash image_count_openai_ladder_251.sh
bash fmt_min_9px_openai_single.sh
bash fmt_min_1px_openai_single.sh
bash fmt_aspect_210_openai_single.sh
bash fmt_corrupt_openai_single.sh
bash fmt_empty_openai_single.sh
bash max_tokens_overflow_openai_single.sh
bash unknown_model_openai_single.sh
bash empty_messages_openai_single.sh
bash text_zh_ext_openai_ladder_4_6.sh
bash image_real_openai_ladder_45.sh
bash image_real_openai_refine_39_25.sh
bash text_en_anthropic_ladder_4_4.sh
bash text_zh_ext_anthropic_ladder_4_6.sh
bash body_size_anthropic_ladder_65.sh
bash image_count_anthropic_ladder_251.sh
bash fmt_min_9px_anthropic_single.sh
bash fmt_min_1px_anthropic_single.sh
bash fmt_aspect_210_anthropic_single.sh
bash fmt_corrupt_anthropic_single.sh
bash fmt_empty_anthropic_single.sh
bash unknown_model_anthropic_single.sh
bash empty_messages_anthropic_single.sh
bash image_real_anthropic_ladder_24_1.sh
bash image_real_anthropic_refine_24.sh
bash image_real_responses_ladder_45.sh
bash image_real_responses_refine_39_25.sh
bash image_count_responses_ladder_251.sh
bash fmt_min_9px_responses_single.sh
bash fmt_min_1px_responses_single.sh
bash fmt_aspect_210_responses_single.sh
bash fmt_corrupt_responses_single.sh
bash fmt_empty_responses_single.sh
bash unknown_model_responses_single.sh
bash empty_messages_responses_single.sh
```

Windows 下把 `bash xxx.sh` 换成 `xxx.cmd` 即可（或在 PowerShell 里执行）。
两者重放的是同一个请求体。
