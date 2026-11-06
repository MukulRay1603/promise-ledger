const form = document.getElementById("ask-form");
const status = document.getElementById("status");
const answerEl = document.getElementById("answer");
const citationsEl = document.getElementById("citations");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  status.textContent = "Looking that up…";
  answerEl.textContent = "";
  citationsEl.replaceChildren();

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: form.question.value }),
    });
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    const data = await res.json();
    answerEl.textContent = data.answer;
    for (const id of data.citations) {
      const li = document.createElement("li");
      li.textContent = id;
      citationsEl.append(li);
    }
    status.textContent = data.needs_human
      ? "Answer ready. Your question may need a person: contact legal aid or call 211."
      : "Answer ready.";
  } catch (err) {
    status.textContent = `Something went wrong: ${err.message}. Please try again.`;
  } finally {
    button.disabled = false;
  }
});
