const API_URL = "/api";

function createBox(obj, text, value) {
  let elem = document.createElement("div");
  elem.innerText = text;
  elem.setAttribute("value", JSON.stringify(value));
  elem.classList.add("result-box");
  elem.onclick = elem.remove;
  obj.parentElement.firstElementChild.appendChild(elem);

  return elem;
}

function calcProfit(elem) {
  elem.disabled = true;
  elem.innerText = "Calculating...";
  fetch(`${API_URL}/profit`).then((r) => {
    r.text().then((total) => {
      let totalSpan = document.createElement("b");
      totalSpan.innerText = `${Number(total).toLocaleString()} aUEC`;
      elem.parentNode.replaceChild(totalSpan, elem);
    });
  });
}

function setCurrentCrew() {
  fetch(`${API_URL}/current_crew`).then((r) =>
    r.json().then((members) => {
      for (let member of members) {
        createBox(document.querySelector("#crew"), member.nick, member);
      }
    })
  );
}

async function splitSearch(
  collection,
  event,
  obj,
  to_str,
  keys = ["Enter", ","]
) {
  if (!keys || keys.includes(event.key)) {
    let value = obj.value.trim();
    obj.value = "";

    let amount = null;
    let resource = null;
    for (let v of value.split(" ")) {
      let _v = v.toLowerCase().replace("scu", "").trim();

      if (_v && _v != "of") {
        let parsed = parseInt(_v);
        if (!isNaN(parsed)) {
          amount = parsed;
        } else {
          resource = v;
        }
      }
    }

    if (amount && resource) {
      let searching_elem = createBox(obj, "Searching...");
      let document = await (
        await fetch(`${API_URL}/search/${collection}/${resource}`, {
          credentials: "include",
        })
      ).json();

      searching_elem.remove();
      createBox(obj, `${to_str(document)} (${amount} SCU)`, {
        resource: document,
        amount: amount,
      });
    }
    return false;
  }
}

async function search(collection, event, obj, to_str, keys = ["Enter", ","]) {
  if (!keys || keys.includes(event.key)) {
    let value = obj.value.trim();
    obj.value = "";

    if (value) {
      if (collection) {
        let searching_elem = createBox(obj, "Searching...");
        let document = await (
          await fetch(`${API_URL}/search/${collection}/${value}`, {
            credentials: "include",
          })
        ).json();

        searching_elem.remove();
        createBox(obj, to_str(document), document);
      } else {
        createBox(obj, value, value);
      }
    }
    return false;
  }
}

async function postToDiscord(form) {
  [...form.getElementsByClassName("autocomplete-input-container")].forEach(
    (i) => i.classList.add("disabled")
  );
  [...form.getElementsByTagName("input")].forEach((i) => (i.disabled = true));

  let body = {};

  for (let container of form.getElementsByTagName("fieldset")) {
    body[container.querySelector("input").name] = [
      ...container.getElementsByClassName("result-box"),
    ].map((r) => JSON.parse(r.getAttribute("value")));
  }

  let screenshot_elem = form.querySelector("#screenshot");
  if (screenshot_elem.files) {
    let screenshot = screenshot_elem.files[0];
    let formData = new FormData();
    formData.append("file", screenshot, screenshot.name);
    let response = await (
      await fetch(`${API_URL}/upload/sc`, {
        method: "PUT",
        body: formData,
      })
    ).json();

    body.screenshot_url = response.image_url;
  } else {
    body.screenshot_url = "";
  }

  await fetch(`${API_URL}/discord`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  [...form.getElementsByClassName("autocomplete-input-container")].forEach(
    (i) => i.classList.remove("disabled")
  );
  [...form.getElementsByTagName("input")].forEach((i) => (i.disabled = false));
  form.querySelector("#screenshot").disabled = true;

  [...form.getElementsByClassName("result-box")].forEach((r) => r.remove());
  setCurrentCrew();
}

setCurrentCrew();
