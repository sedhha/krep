"use client";

import { type ApiError, type AuthAdapter, type JsonSchema } from "../lib/api";

import { Input } from "./ui/input";

function concrete(schema: JsonSchema): JsonSchema {
  return schema.anyOf?.find((item) => item.type !== "null") ?? schema;
}

export function readAdapterForm(form: HTMLFormElement, adapter: AuthAdapter) {
  const data = new FormData(form);
  const config: Record<string, unknown> = {};
  let secret: string | undefined;
  for (const [name, field] of Object.entries(adapter.config_schema.properties ?? {})) {
    const schema = concrete(field);
    const key = `auth.${name}`;
    const value = data.get(key);
    if (adapter.secret_fields.includes(name) || field.writeOnly) {
      if (typeof value === "string" && value) secret = value;
      const input = form.elements.namedItem(key);
      if (input instanceof HTMLInputElement) input.value = "";
    } else if (schema.type === "boolean") {
      config[name] = value === "on";
    } else if (schema.type === "array" && schema.items?.enum) {
      const selected = data.getAll(key);
      if (selected.length || adapter.config_schema.required?.includes(name)) config[name] = selected;
    } else if (typeof value === "string" && value !== "") {
      config[name] = schema.type === "array" ? value.split(",").map((v) => v.trim()).filter(Boolean)
        : ["integer", "number"].includes(schema.type ?? "") ? Number(value) : value;
    }
  }
  return { adapter: adapter.type, config, ...(secret ? { secret } : {}) };
}

export function AdapterForm({ adapter, values = {}, error }: {
  adapter: AuthAdapter;
  values?: Record<string, unknown>;
  error?: ApiError | null;
}) {
  const errors = error?.error === "auth_config_invalid"
    ? error.detail.errors as { field: string; message: string }[] | undefined : undefined;
  return (
    <fieldset>
      <legend>Authentication configuration</legend>
      {Object.entries(adapter.config_schema.properties ?? {}).map(([name, field]) => {
        const schema = concrete(field);
        const secret = adapter.secret_fields.includes(name) || field.writeOnly;
        const value = secret ? "" : values[name] ?? field.default ?? "";
        const label = field.title ?? name.replaceAll("_", " ");
        const message = errors?.filter((e) => e.field.split(".")[0] === name).map((e) => e.message).join("; ");
        const id = `auth.${name}`;
        const required = adapter.config_schema.required?.includes(name);
        return <div key={name} className="space-y-2">
          {schema.type === "array" && schema.items?.enum ? <fieldset>
            <legend>{label}</legend>
            {schema.items.enum.map((option) => <label key={option} className="!flex items-center gap-2">
              <input name={id} type="checkbox" value={option} defaultChecked={Array.isArray(value) && value.includes(option)} />{option}
            </label>)}
          </fieldset> : <label htmlFor={id}>{label}
            {schema.enum ? <select id={id} name={id} defaultValue={String(value)} required={required}>
              {schema.enum.map((option) => <option key={option}>{option}</option>)}
            </select> : schema.type === "boolean" ? <input id={id} name={id} type="checkbox" defaultChecked={value === true} />
              : <Input id={id} name={id} type={secret ? "password" : ["integer", "number"].includes(schema.type ?? "") ? "number" : "text"}
                defaultValue={Array.isArray(value) ? value.join(", ") : String(value)} required={required}
                autoComplete={secret ? "new-password" : "off"} min={schema.minimum} max={schema.maximum}
                minLength={schema.minLength} maxLength={schema.maxLength}
                step={schema.type === "number" ? "any" : undefined}
                aria-invalid={!!message} aria-describedby={message ? `${id}.error` : undefined} />}
          </label>}
          {field.description && <small>{field.description}</small>}
          {schema.type === "array" && !schema.items?.enum && <small>Separate values with commas.</small>}
          {message && <p role="alert" id={`${id}.error`}>{message}</p>}
        </div>;
      })}
    </fieldset>
  );
}
