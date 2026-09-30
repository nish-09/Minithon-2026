"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-700 to-cyan-700 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div>
          <p className="text-3xl font-extrabold tracking-tight">NEXA</p>
          <p className="mt-1 text-indigo-100">Your Neighborhood, When You Need It Most.</p>
        </div>
        <div className="space-y-5">
          {[
            ["Ask", "Say it or type it. No long forms."],
            ["Understand", "NEXA works out what you need and how urgent it is."],
            ["Match", "The right nearby person, weighed by skill, distance and trust."],
            ["Connect", "Your Trusted Circle first, if you want."],
            ["Care", "Voice-guided support until real help arrives."],
          ].map(([t, d]) => (
            <div key={t} className="flex gap-4">
              <span className="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white/15 text-sm font-bold">{t[0]}</span>
              <p>
                <b>{t}.</b> <span className="text-indigo-100">{d}</span>
              </p>
            </div>
          ))}
        </div>
        <p className="text-xs text-indigo-200">NEXA connects neighbours. It does not replace emergency services.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <p className="mb-6 text-center text-3xl font-extrabold tracking-tight text-brandtext lg:hidden">NEXA</p>
          {children}
        </div>
      </div>
    </div>
  );
}
