document.addEventListener("DOMContentLoaded", () => { 
    const form = document.querySelector("form");
    const signinButton = document.getElementById("signinbutton");
    const spinner = document.getElementById("spinner");
    const progressMessage = document.getElementById("progress-message");

    form.addEventListener("submit", async (event) => {
        event.preventDefault(); // 阻止表单默认提交

        const username = document.getElementById("username").value.trim();
        const password = document.getElementById("password").value;
        const staySignedIn = document.getElementById("staySignedIn").checked;
        const urlParams = new URLSearchParams(window.location.search);
        const nextUrl = urlParams.get("next") || "/dashboard";

        if (!username || !password) {
            alert("Please enter username and password.");
            return;
        }

        // 显示加载动画
        spinner.classList.remove("signin-hidden");
        progressMessage.textContent = "Signing in...";

        try {
            const response = await fetch("/api/login", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                credentials: "include", // 允许携带 Cookie
                body: JSON.stringify({
                    username,
                    password,
                    staySignedIn,
                    next: nextUrl 
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                // 如果后端返回了 redirect 字段，就跳转到它，否则回 dashboard
                if (result.redirect) {
                    window.location.href = result.redirect;
                } else {
                    window.location.href = "/dashboard";
                }
            } else {
                spinner.classList.add("signin-hidden");
                progressMessage.textContent = "";

                const errorPanel = document.getElementById("errorpanel");
                const errorText = document.getElementById("errortext");

                if (errorText) {
                    errorText.textContent = "Error: " + (result.message || "Login failed");
                } else {
                // 如果模板里没渲染 errorpanel，就动态插入
                    const panel = document.createElement("div");
                    panel.id = "errorpanel";
                    panel.innerHTML = `<p id="errortext">Error: ${result.message || "Login failed"}</p>`;
                    form.parentNode.insertBefore(panel, form);
                }
    	    }
        } catch (error) {
            spinner.classList.add("signin-hidden");
            progressMessage.textContent = "";
            console.error("Login error:", error);
            alert("Network error, please try again.");
        }
    });
});
