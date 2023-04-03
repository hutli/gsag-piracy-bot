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

async function splitSearch(collection, event, obj, main_key, keys = ["Enter"]) {
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
      createBox(obj, `${document[main_key]} (${amount} SCU)`, {
        resource: document,
        amount: amount,
      });
    }
    return false;
  }
}

async function search(collection, event, obj, main_key, keys = ["Enter"]) {
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
        createBox(obj, document[main_key], document);
      } else {
        createBox(obj, value, value);
      }
    }
    return false;
  }
}

async function postToDiscord(form) {
  let body = {};

  for (let container of form.getElementsByTagName("fieldset")) {
    console.log(container);
    body[container.querySelector("input").name] = [
      ...container.getElementsByClassName("result-box"),
    ].map((r) => JSON.parse(r.getAttribute("value")));
  }

  console.log(body);

  let response = await fetch(`${API_URL}/discord`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  console.log(await response.text());
}

fetch(`${API_URL}/current_crew`, { credentials: "include" }).then((r) =>
  r.json().then((members) => {
    for (let member of members) {
      createBox(document.querySelector("#crew"), member.nick, member);
    }
  })
);
