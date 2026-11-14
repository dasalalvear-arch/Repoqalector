"""Cliente minimo para endpoints de chat compatibles con el formato de OpenAI.

Gemini, Groq, Together y OpenRouter exponen ese formato, asi que cambiar de
proveedor es cambiar base_url, key y modelo — no de codigo.

repoqa: urllib de la stdlib en vez de un SDK. Sin streaming, sin reintentos,
sin pool de conexiones. Si se agrega streaming o hace falta reintentar ante
429, ahi se justifica httpx.
"""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    """El proveedor fallo, expiro o devolvio algo que no se pudo leer."""


def chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 60.0,
) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Algunos proveedores detras de Cloudflare rechazan el User-Agent
            # por defecto de urllib con un 403.
            "User-Agent": "repoqa/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return data["choices"][0]["message"]["content"] or ""
    except urllib.error.HTTPError as error:
        # El cuerpo dice que limite se toco o que modelo no existe; sin el, un
        # 429 o un 404 no se pueden diagnosticar. Va al log, nunca al cliente.
        detail = " ".join(error.read().decode(errors="replace").split())[:500]
        raise LLMError(f"HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as error:
        raise LLMError(str(error)) from error
