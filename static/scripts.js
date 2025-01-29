
async function askQuestion(playerId, playerName) {
  const question = prompt(`Ask a question about ${playerName}:`);
  if (!question) return;

  try {
    const response = await fetch(`/api/ask/${playerId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });

    const data = await response.json();
    if (data.error) {
      alert(`Error: ${data.error}`);
    } else {
      alert(data.answer);
    }
  } catch (error) {
    console.error('Error asking question:', error);
    alert('Error processing question');
  }
}

function closeModal() {
  document.getElementById("sentimentModal").style.display = "none";
  // Refresh the page to show updated cache status
  window.location.reload();
}

function loadStats(playerId, playerName) {
  const modalContent = document.getElementById("sentimentModalContent");
  modalContent.innerHTML = `
    <div class="loader-container">
      <div class="loader"></div>
    </div>
  `;
  document.getElementById("sentimentModal").style.display = "block";

  fetch(`/stats/${playerId}`)
    .then(response => {
      window.location.href = `/stats/${playerId}`;
    })
    .catch(error => {
      console.error('Error:', error);
      document.getElementById("sentimentModal").style.display = "none";
      alert('Error loading stats. Please try again.');
    });
}

function loadVideo(playerId, playerName) {
  const modalContent = document.getElementById("sentimentModalContent");
  modalContent.innerHTML = `
    <div class="loader-container">
      <div class="loader"></div>
    </div>
  `;
  document.getElementById("sentimentModal").style.display = "block";

  fetch(`/video/${playerId}`)
    .then(response => {
      if (response.status === 404) {
        document.getElementById("sentimentModal").style.display = "none";
        alert(`No home run videos found in the archive for ${playerName}`);
        return;
      }
      window.location.href = `/video/${playerId}`;
    })
    .catch(error => {
      console.error('Error:', error);
      document.getElementById("sentimentModal").style.display = "none";
      alert('Error loading video. Please try again.');
    });
}

document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('playerForm');
  const loader = document.getElementById('addPlayerLoader');

  if (form) {
    form.addEventListener('submit', function() {
      loader.style.display = 'block';
    });
  }
});

function filterPlayers(searchTerm) {
  const playerList = document.querySelectorAll('.player-item');
  searchTerm = searchTerm.toLowerCase();

  playerList.forEach(item => {
    const playerName = item.querySelector('.player-info').textContent.toLowerCase();
    if (playerName.includes(searchTerm)) {
      item.style.display = '';
    } else {
      item.style.display = 'none';
    }
  });
}

function loadPredict(playerId, playerName) {
  window.location.href = `/predict/${playerId}`;
}

function loadNextVideo(playerId, videoIndex) {
    if (!playerId) {
        console.error('Player ID is undefined');
        return;
    }
    const loader = document.getElementById('nextVideoLoader');
    if (loader) {
        loader.style.display = 'block';
    }
    const analysisUrl = `/api/analysis/${playerId}/${videoIndex}`;

    fetch(analysisUrl)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error loading analysis:', data.error);
            } else {
                window.location.href = `/video/${playerId}/${videoIndex}`;
            }
        })
        .catch(error => {
            console.error('Error loading analysis:', error);
            window.location.href = `/video/${playerId}/${videoIndex}`;
        });
}