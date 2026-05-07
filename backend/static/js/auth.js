document.querySelectorAll(".password-toggle").forEach(function(toggle) {
  toggle.addEventListener("click", function() {
    const input = document.getElementById(toggle.dataset.target);
    const icon = toggle.querySelector("i");

    if (!input) {
      return;
    }

    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    toggle.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");

    if (icon) {
      icon.classList.toggle("fa-eye", !isHidden);
      icon.classList.toggle("fa-eye-slash", isHidden);
    }
  });
});
