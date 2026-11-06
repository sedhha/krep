"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AdapterForm, readAdapterForm } from "@/components/AdapterForm";
import { Button } from "@/components/ui/button";
import { ErrorMessage } from "@/components/ui/console";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, adminApi } from "@/lib/api";

const DEFAULT_RULES = {
  "registry-admins": '"org-admin" in token.groups',
  "registry-writers": '"org-admin" in token.groups || "writer" in token.groups',
  "registry-readers": '"org-admin" in token.groups || "writer" in token.groups || "reader" in token.groups',
};

export default function CreateOrganizationPage() {
  const router = useRouter();
  const client = useQueryClient();
  const adapters = useQuery({ queryKey: ["auth-adapters"], queryFn: adminApi.adapters });
  const [step, setStep] = useState(0);
  const [adapterType, setAdapterType] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const adapter = adapters.data?.items.find((a) => a.type === adapterType);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true);
    setError(null);
    try {
      const org = await adminApi.createOrganization({
        slug: String(data.get("slug")), name: String(data.get("name")), admin_user: String(data.get("admin_user")),
        capabilities: Object.fromEntries(Object.keys(DEFAULT_RULES).map((name) => [name, String(data.get(name))])),
        ...(adapter ? { auth: readAdapterForm(form, adapter) } : {}),
      });
      await client.invalidateQueries({ queryKey: ["organizations"] });
      router.push(`/platform/organizations/${org.id}`);
    } catch (e) { setError(e); }
    finally { setPending(false); }
  }
  return <><h1>New organisation</h1><p className="mb-4">Step {step + 1} of 3 · {['Details', 'Authentication', 'Capabilities and create'][step]}</p>
    <section><ErrorMessage error={error ?? adapters.error} />
      <form onSubmit={submit}>
        <fieldset hidden={step !== 0} className={step !== 0 ? "!hidden" : ""}>
          <label>Slug<Input name="slug" pattern="[a-z0-9][a-z0-9-]{1,62}" required /></label>
          <label>Name<Input name="name" maxLength={120} required /></label>
          <label>First admin username<Input name="admin_user" required /></label>
        </fieldset>
        <fieldset hidden={step !== 1} className={step !== 1 ? "!hidden" : ""}>
          <label>Authentication adapter<select value={adapterType} onChange={(e) => setAdapterType(e.target.value)} disabled={adapters.isPending || pending}>
            <option value="">Panel login only</option>{adapters.data?.items.map((a) => <option key={a.type} value={a.type}>{a.type}</option>)}
          </select></label>
        </fieldset>
        {step === 2 && <>
          {adapter && <AdapterForm key={adapter.type} adapter={adapter} error={error instanceof ApiError ? error : null} />}
          <fieldset><legend>Capability policies</legend>{Object.entries(DEFAULT_RULES).map(([name, rule]) => <label key={name}>{name}<Textarea name={name} defaultValue={rule} required /></label>)}</fieldset>
          <p>The first administrator receives the org-admin group. Secret fields clear when submitted.</p>
        </>}
        <div className="actions">
          {step > 0 && <Button type="button" variant="outline" disabled={pending} onClick={() => setStep(step - 1)}>Back</Button>}
          {step < 2 ? <Button type="button" onClick={(e) => {
            const form = e.currentTarget.form;
            if (form === null) return;
            const current = form.querySelectorAll<HTMLInputElement>("fieldset:not([hidden]) input[required]");
            if (Array.from(current).every((input) => input.reportValidity())) setStep(step + 1);
          }}>Next</Button> : <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create organisation"}</Button>}
        </div>
      </form>
    </section></>;
}
