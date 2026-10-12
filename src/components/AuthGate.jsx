import { LogIn, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { supabase } from "../lib/supabase";
import { userFacingDataError } from "../utils/dataError";

export default function AuthGate({ children }) {
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    supabase.auth.getSession().then(({ data, error: sessionError }) => {
      if (!mounted) return;
      if (sessionError) {
        setError(userFacingDataError(sessionError, "Could not verify your session."));
      }
      setSession(data.session ?? null);
      setChecking(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, nextSession) => {
        if (mounted) {
          setSession(nextSession);
          setChecking(false);
        }
      }
    );

    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  async function handleSignIn(event) {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError("");
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signInError) throw signInError;
    } catch (signInError) {
      setError(userFacingDataError(signInError, "Could not sign in."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSignOut() {
    setError("");
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) {
      setError(userFacingDataError(signOutError, "Could not sign out."));
    }
  }

  if (checking) {
    return (
      <main className="auth-shell">
        <section className="card auth-card auth-checking">
          <ShieldCheck size={24} />
          <strong>Checking secure session…</strong>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <form className="card auth-card" onSubmit={handleSignIn}>
          <div className="auth-heading">
            <ShieldCheck size={25} />
            <div>
              <p className="eyebrow">Private dashboard</p>
              <h1>Sign in</h1>
            </div>
          </div>

          <p className="auth-caption">
            Use the dashboard account created in Supabase Authentication.
          </p>

          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label>
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error ? <p className="auth-error">{error}</p> : null}

          <button type="submit" disabled={submitting}>
            <LogIn size={16} />
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <>
      <button type="button" className="sign-out-button" onClick={handleSignOut}>
        <LogOut size={14} />
        Sign out
      </button>
      {error ? <p className="auth-global-error">{error}</p> : null}
      {children}
    </>
  );
}
