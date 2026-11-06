// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, assert, expect, it } from "vitest";

import { AdapterForm, readAdapterForm } from "../../src/components/AdapterForm";
import { ApiError, type AuthAdapter } from "../../src/lib/api";

afterEach(cleanup);

const adapter: AuthAdapter = {
  type: "test",
  secret_fields: ["secret"],
  config_schema: {
    type: "object", required: ["secret", "audience"],
    properties: {
      secret: { type: "string", title: "Secret", writeOnly: true, format: "password" },
      audience: { type: "string", title: "Audience" },
      algorithms: { type: "array", title: "Algorithms", items: { type: "string", enum: ["HS256", "HS512"] }, default: ["HS256"] },
      user_claim_path: { type: "array", title: "User claim path", items: { type: "string" }, default: ["sub"] },
      allow_principal: { type: "boolean", title: "Allow principal", default: false },
      retries: { type: "integer", title: "Retries", minimum: 1, maximum: 5, default: 2 },
      issuer: { anyOf: [{ type: "string" }, { type: "null" }], title: "Issuer", default: null },
    },
  },
};

it("renders schema defaults and excludes secrets from existing values", () => {
  render(<AdapterForm adapter={adapter} values={{ audience: "krep", secret: "never-render-this" }} />);
  expect((screen.getByLabelText("Secret") as HTMLInputElement).type).toBe("password");
  expect((screen.getByLabelText("Secret") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("Audience") as HTMLInputElement).value).toBe("krep");
  expect((screen.getByLabelText("HS256") as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText("Retries") as HTMLInputElement).min).toBe("1");
  expect(document.body.innerHTML).not.toContain("never-render-this");
});

it("reads typed config and immediately clears secret inputs", () => {
  const { container } = render(<form><AdapterForm adapter={adapter} /></form>);
  fireEvent.change(screen.getByLabelText("Secret"), { target: { value: "write-only-secret" } });
  fireEvent.change(screen.getByLabelText("Audience"), { target: { value: "registry" } });
  fireEvent.click(screen.getByLabelText("HS512"));
  fireEvent.click(screen.getByLabelText("Allow principal"));
  const form = container.querySelector("form");
  assert(form instanceof HTMLFormElement);
  expect(readAdapterForm(form, adapter)).toEqual({
    adapter: "test", secret: "write-only-secret", config: {
      audience: "registry", algorithms: ["HS256", "HS512"], user_claim_path: ["sub"], allow_principal: true, retries: 2,
    },
  });
  expect((screen.getByLabelText("Secret") as HTMLInputElement).value).toBe("");
});

it("shows backend auth_config_invalid field errors next to inputs", () => {
  const error = new ApiError(422, "auth_config_invalid", "invalid auth config", {
    errors: [{ field: "secret", message: "secret must be at least 32 bytes" }],
  });
  render(<AdapterForm adapter={adapter} error={error} />);
  expect(screen.getByRole("alert").textContent).toBe("secret must be at least 32 bytes");
  expect(screen.getByLabelText("Secret").getAttribute("aria-invalid")).toBe("true");
});
