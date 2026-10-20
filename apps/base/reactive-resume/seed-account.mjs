// Creates the owner's password account once; a successful sign-in means it already exists.
const { APP_URL, BASE_URL, EMAIL, PASSWORD } = process.env;
for (const [name, value] of Object.entries({ APP_URL, BASE_URL, EMAIL, PASSWORD })) {
  if (!value) throw new Error(`${name} is required`);
}

const post = (path, body) =>
  fetch(`${BASE_URL}/api/auth${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: APP_URL },
    body: JSON.stringify(body),
  });

for (let attempt = 1; ; attempt++) {
  const health = await fetch(`${BASE_URL}/api/health`).catch(() => undefined);
  if (health?.ok) break;
  if (attempt === 60) throw new Error("Reactive Resume did not become healthy");
  await new Promise((resolve) => setTimeout(resolve, 5000));
}

if ((await post("/sign-in/email", { email: EMAIL, password: PASSWORD })).ok) {
  console.log("Owner account already exists");
  process.exit(0);
}

const username = EMAIL.split("@")[0];
const signUp = await post("/sign-up/email", {
  email: EMAIL,
  password: PASSWORD,
  name: username,
  username,
});
if (signUp.ok) {
  console.log("Created owner account");
  process.exit(0);
}
const error = await signUp.json().catch(() => ({}));
// An account created through Pocket ID has no password; its owner sets one with "Forgot password".
if (error.code === "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL") {
  console.log("Owner account exists without this password; set it with Forgot password");
  process.exit(0);
}
throw new Error(`Sign-up failed with HTTP ${signUp.status}: ${error.message ?? "unknown error"}`);
