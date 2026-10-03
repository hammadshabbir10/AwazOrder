"use strict";

const $ = (id) => document.getElementById(id);
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function setError(input, message) {
  $(`${input}-error`).textContent = message;
  $(input).setAttribute("aria-invalid", message ? "true" : "false");
}

function validate() {
  const email = $("email").value.trim();
  const password = $("password").value;
  let ok = true;
  if (!email) { setError("email", "Enter your email address."); ok = false; }
  else if (!EMAIL_RE.test(email)) { setError("email", "That doesn't look like an email address."); ok = false; }
  else setError("email", "");
  if (!password) { setError("password", "Enter your password."); ok = false; }
  else setError("password", "");
  return ok;
}

["email", "password"].forEach((id) => $(id).addEventListener("input", () => {
  if ($(id).getAttribute("aria-invalid") === "true") validate();
  $("form-error").textContent = "";
}));

$("pw-toggle").onclick = () => {
  const show = $("password").type === "password";
  $("password").type = show ? "text" : "password";
  $("pw-toggle").textContent = show ? "Hide" : "Show";
  $("pw-toggle").setAttribute("aria-label", show ? "Hide password" : "Show password");
};

$("fill-demo").onclick = () => {
  $("email").value = "demo@awazorder.pk";
  $("password").value = "Demo@1234";
  validate();
  $("submit").focus();
};

$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("form-error").textContent = "";
  if (!validate()) return;
  const btn = $("submit");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Signing in…';
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("email").value.trim(), password: $("password").value }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Sign-in failed. Please try again.");
    location.href = "/app";
  } catch (err) {
    $("form-error").textContent = err.message === "Failed to fetch" ? "Can't reach the server. Check your connection and try again." : err.message;
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
};
