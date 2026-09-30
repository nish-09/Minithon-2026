"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ name: "", email: "", phone: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Record<string, string> = {};
    if (f.name.trim().length < 2) local.name = "Please enter your name.";
    if (!/^\S+@\S+\.\S+$/.test(f.email)) local.email = "Enter a valid email address.";
    if (f.password.length < 8) local.password = "Use at least 8 characters.";
    if (f.phone && !/^\+?[0-9][0-9 \-]{6,18}$/.test(f.phone)) local.phone = "Enter a valid phone number, e.g. +91 98765 43210.";
    setFieldErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      await register({ name: f.name.trim(), email: f.email.trim(), password: f.password, ...(f.phone ? { phone: f.phone } : {}) });
      router.replace("/?welcome=1");
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) setFieldErrors(Object.fromEntries(err.fieldErrors.map((x) => [x.field, x.message])));
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Join your neighborhood</h1>
      <p className="mt-1 text-muted">Ask for help. Offer help. Know who you can count on.</p>
      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}
        <Field label="Full name" required error={fieldErrors.name}>{(id, a) => <Input id={id} {...a} autoComplete="name" value={f.name} onChange={set("name")} />}</Field>
        <Field label="Email" required error={fieldErrors.email}>{(id, a) => <Input id={id} {...a} type="email" autoComplete="email" value={f.email} onChange={set("email")} />}</Field>
        <Field label="Phone (optional)" hint="Used for verification. Never shown to other members." error={fieldErrors.phone}>{(id, a) => <Input id={id} {...a} type="tel" autoComplete="tel" value={f.phone} onChange={set("phone")} />}</Field>
        <Field label="Password" required hint="At least 8 characters." error={fieldErrors.password}>{(id, a) => <Input id={id} {...a} type="password" autoComplete="new-password" value={f.password} onChange={set("password")} />}</Field>
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already a member?{" "}
        <Link href="/login" className="font-semibold text-brandtext underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
