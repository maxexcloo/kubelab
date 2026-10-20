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
if (!signUp.ok)
  throw new Error(`Sign-up failed with HTTP ${signUp.status}: ${await signUp.text()}`);
console.log("Created owner account");
