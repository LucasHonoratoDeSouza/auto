const form = document.getElementById("access-form");
const feedback = document.getElementById("form-feedback");

if (form && feedback) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const data = new FormData(form);
    const values = Object.fromEntries(data.entries());

    const subject = `[Access request] ${values.full_name} · ${values.tiktok_handle}`;
    const body = [
      "Linvesther Studio access request",
      "",
      `Full name: ${values.full_name}`,
      `Email: ${values.email}`,
      `TikTok handle: ${values.tiktok_handle}`,
      `Primary channel URL: ${values.channel_url}`,
      `Company or brand: ${values.company || "-"}`,
      `Rights model: ${values.rights_model}`,
      `Estimated posts per week: ${values.posts_per_week}`,
      `Team size: ${values.team_size || "-"}`,
      "",
      "Use case:",
      values.use_case,
      "",
      `Rights confirmation: ${values.rights_confirmation ? "Yes" : "No"}`,
    ].join("\n");

    try {
      await navigator.clipboard.writeText(body);
      feedback.textContent = "Request copied. Your email app is opening now.";
    } catch {
      feedback.textContent = "Your email app is opening now.";
    }

    window.location.href =
      `mailto:linvesther@gmail.com?subject=${encodeURIComponent(subject)}` +
      `&body=${encodeURIComponent(body)}`;
  });
}
