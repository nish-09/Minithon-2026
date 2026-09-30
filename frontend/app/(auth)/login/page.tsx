"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 0 ? err.message : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Welcome back</h1>
      <p className="mt-1 text-muted">Log in to reach your neighborhood.</p>
      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}
        <Field label="Email">{(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password">{(id) => <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!email || !password}>
          Log in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        New to NEXA?{" "}
        <Link href="/register" className="font-semibold text-brandtext underline">
          Create an account
        </Link>
      </p>
      <p className="mt-8 rounded-xl bg-surface2 p-3 text-center text-xs text-muted">
        Demo data: <code>nishit@nexa-demo.app</code> / <code>nexa1234</code> (run <code>python -m app.seed</code> in the backend)
      </p>
    </div>
  );
}
