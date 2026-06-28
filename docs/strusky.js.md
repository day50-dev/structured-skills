# strusky.js

Client-side JS library for working with strusky (`.ss`) scripts in the browser.

## API

### `strusky.parseInputSpecs(content)`

Parses `.ss` script content and extracts declared input variables.

```js
const specs = strusky.parseInputSpecs(`
input $REPO_FILE as file
input $USERNAME as string
input $THRESHOLD as number
`);
// Returns:
// [
//   { name: "REPO_FILE", type: "file" },
//   { name: "USERNAME",  type: "string" },
//   { name: "THRESHOLD", type: "number" }
// ]
```

Matches lines matching `input $NAME as TYPE` and returns an array of `{ name, type }` objects.

### `strusky.parseOutputSpecs(content)`

Parses `.ss` script content and extracts declared output variables.

```js
const outputs = strusky.parseOutputSpecs(`
output $result as string: register
output $data as file
`);
// Returns:
// [
//   { name: "result", type: "string", register: "register" },
//   { name: "data",   type: "file",   register: "" }
// ]
```

Matches lines matching `output $NAME as TYPE: register` and returns `{ name, type, register }`.

### `strusky.serve(code, input, opts?)`

Sends a strusky script and its inputs to a server endpoint for execution.

```js
const result = await strusky.serve(
  `input $TOPIC as string\n$prompt = $TOPIC`,
  { TOPIC: "AI Safety" }
);
console.log(result.registers.$prompt); // "AI Safety"
```

**Arguments:**
- `code` — the `.ss` script source as a string
- `input` — object mapping input names to values
- `opts.endpoint` — server URL (default `"/api/serve"`)

**Returns:** a promise resolving to `{ registers, tokens, progress }`

The server endpoint should accept `POST { code, input }` and return the execution result.

---

## Frontend Usage

The library is loaded in `frontend/index.html`:

```html
<script src="strusky.js"></script>
```

The frontend uses `parseInputSpecs` to derive typed input fields from the script content whenever an agent is selected:

```js
currentInputSpecs = strusky.parseInputSpecs(data.content);
renderInputSpecs();
```

This replaces the previous server-only input spec parsing — typed inputs (string, number, file, repo) are now inferred client-side from the script itself, enabling the UI to render the correct form controls before the user hits Run.
