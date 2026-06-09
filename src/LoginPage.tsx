import { useState } from "react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    console.log("Sign in submitted", { email, password });
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <section className="mx-auto flex min-h-screen max-w-6xl items-center px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid w-full overflow-hidden rounded-2xl bg-white shadow-xl lg:grid-cols-2">
          <div className="relative hidden bg-slate-900 p-10 text-white lg:block">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.25),transparent_55%)]" />
            <div className="relative z-10">
              <h1 className="text-3xl font-semibold tracking-tight">Welcome back</h1>
              <p className="mt-4 max-w-sm text-slate-200">
                Sign in to continue managing your workspace, projects, and team activity.
              </p>
              <ul className="mt-10 space-y-3 text-sm text-slate-200">
                <li>Secure account access</li>
                <li>Team and project visibility</li>
                <li>Fast, responsive dashboard</li>
              </ul>
            </div>
          </div>

          <div className="p-6 sm:p-10 lg:p-12">
            <div className="mx-auto w-full max-w-md">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in</h2>
              <p className="mt-2 text-sm text-slate-600">
                Use your email and password to access your account.
              </p>

              <form onSubmit={handleSubmit} className="mt-8 space-y-5" noValidate>
                <div>
                  <label htmlFor="email" className="mb-2 block text-sm font-medium text-slate-700">
                    Email
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 outline-none ring-sky-500 transition focus:border-sky-500 focus:ring-2"
                    placeholder="name@company.com"
                  />
                </div>

                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <label htmlFor="password" className="block text-sm font-medium text-slate-700">
                      Password
                    </label>
                    <a
                      href="/forgot-password"
                      className="text-sm font-medium text-sky-700 hover:text-sky-800 hover:underline"
                    >
                      Forgot password?
                    </a>
                  </div>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 outline-none ring-sky-500 transition focus:border-sky-500 focus:ring-2"
                    placeholder="Enter your password"
                  />
                </div>

                <button
                  type="submit"
                  className="inline-flex w-full items-center justify-center rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:ring-offset-2"
                >
                  Sign in
                </button>
              </form>

              <p className="mt-6 text-center text-sm text-slate-600">
                New here?{" "}
                <a href="/signup" className="font-medium text-sky-700 hover:underline">
                  Create an account
                </a>
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
