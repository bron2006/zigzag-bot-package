async function updateStatus() {
  try {
    const res = await fetch("/status");
    const data = await res.json();
    document.getElementById("status").innerText = data.status;
    document.getElementById("status").style.color = 
      data.status === "авторизований" ? "#00e676" : "#ff1744";
  } catch (e) {
    document.getElementById("status").innerText = "Помилка";
    document.getElementById("status").style.color = "#ff1744";
  }
}

// Оновлюємо статус кожні 5 секунд
setInterval(updateStatus, 5000);
updateStatus();
