# strusky Server API

The strusky server runs `.ss` code remotely via HTTP. Start it with:

```bash
strusky server --port 8081
# or
strusky-server --port 8081
```

## Endpoints

### `GET /`

Server health check. Returns basic server info.

### `GET /openapi.json`

Returns the OpenAPI 3.1 spec for the server API.

### `GET /docs`

Swagger UI for interactive API exploration.

### `POST /run`

Execute a strusky script with optional inputs.

**Request body:**

```json
{
  "code": "strusky script content",
  "input": {
    "name": "value",
    "age": "30"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | The `.ss` script source code to execute |
| `input` | object | no | Key-value pairs mapped to `input $REG as TYPE` specs, or to registers directly |

**Input mapping:**

If the script declares `input $NAME as TYPE` lines, the `input` dict values are mapped to those declared registers. Otherwise, each key in `input` is written directly as `$key = "value"` and prepended to the script.

**Response:**

```json
{
  "registers": {
    "$result": "output value",
    "$debug": "..."
  },
  "tokens": [
    {
      "prompt": 150,
      "completion": 42,
      "total": 192
    }
  ],
  "progress": "stderr output from execution"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `registers` | object | Final state of all VM registers after execution |
| `tokens` | array | Per-inference token usage (empty if no LLM calls) |
| `progress` | string | Stderr output captured during execution (status messages, debug info) |

**Error responses:**

- `400` — `code` field is missing
- `500` — Execution error with message in `error` field

## Example

```bash
curl -X POST http://localhost:8081/run \
  -H "Content-Type: application/json" \
  -d '{
    "code": "input $name as string\n$result = \"Hello, $name!\"",
    "input": { "name": "World" }
  }'
```

```json
{
  "registers": { "$name": "World", "$result": "Hello, World!" },
  "tokens": [],
  "progress": ""
}
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8081` | TCP port to listen on |
| `--host` | `0.0.0.0` | Interface to bind to |
| `--config` | `config.toml` | Path to strusky config file |
