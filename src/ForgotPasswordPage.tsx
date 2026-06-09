import { useState } from "react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    console.log("Password reset requested", { email });
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 sm:px-6 lg:px-8">
      <section className="mx-auto max-w-md rounded-2xl bg-white p-6 shadow-lg sm:p-8">
        <h1 className="text-2xl font-semibold text-slate-900">Reset your password</h1>
        <p className="mt-2 text-sm text-slate-600">
          Enter your account email and we will send you a reset link.
        </p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
          <div>
            <label htmlFor="reset-email" className="mb-2 block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="reset-email"
              name="reset-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
              className="block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 outline-none ring-sky-500 transition focus:border-sky-500 focus:ring-2"
            />
          </div>

          <button
            type="submit"
            className="inline-flex w-full items-center justify-center rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:ring-offset-2"
          >
            Send reset link
          </button>
        </form>

        <a href="/login" className="mt-6 inline-block text-sm font-medium text-sky-700 hover:underline">
          Back to sign in
        </a>
      </section>
    </main>
  );
}
