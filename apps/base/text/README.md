# text

OpenAI-compatible chat completions from a menu of models on the GPU nodes.

The post-renderer in `helm-release.yaml` sets every Deployment to zero replicas,
so a model runs only after it is scaled by hand and stops again on the next
release upgrade. Start one with:

```shell
kubectl -n text scale deployment text-<controller> --replicas=1
```

Models share the GPU claims on their node, so run one at a time. The gaming
models only schedule while `mandu` is online.

| Controller        | Served name                    | Runtime   | GPUs | Notes                              |
| ----------------- | ------------------------------ | --------- | ---- | ---------------------------------- |
| `gemma`           | `gemma-4-31b-heretic`          | radiance  | 1    | 169k context, 2 sequences          |
| `gemma-tp2`       | `gemma-4-31b-heretic`          | radiance  | 2    | 262k context, 8 sequences          |
| `gemma-26b`       | `gemma-4-26b-a4b`              | llama.cpp | 1    | gaming node; vision encoder on CPU |
| `maya`            | `glm-5.3-flash`                | maya      | 2    | expert tiering; 150 s shutdown     |
| `qwen-35b`        | `qwen3.6-35b-a3b`              | llama.cpp | 1    | gaming node; MTP draft             |
| `qwen-flash-next` | `qwen3.8-flash-next`           | radiance  | 2    | expert tiered; TP wire `wht6`      |
| `qwen-fp8`        | `qwen3.8-27b-uncensored-fp8`   | radiance  | 1    | `k6_v4` KV cache                   |
| `qwen-fp8-tp2`    | `qwen3.8-27b-uncensored-fp8`   | radiance  | 2    | 262k context, 8 sequences          |
| `qwen-mxfp4`      | `qwen3.8-27b-uncensored-mxfp4` | radiance  | 1    | embeddings in RAM                  |

`services.yaml` gives every model label a Service. The `text` Service selects
all of them, so `ai/text` reaches whichever model is running; Bifrost routes
provider names to the per-model Services.

The two TP pairs (`gemma`/`gemma-tp2` and `qwen-fp8`/`qwen-fp8-tp2`) are the
same model on one or two GPUs. They cannot be merged into one controller without
giving up one of the placements.
