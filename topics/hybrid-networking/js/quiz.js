function startQuiz(svg, onExit) {
  const panel = document.getElementById('panel');
  const controls = document.getElementById('controls');
  const questions = QUIZ_QUESTIONS.slice(); // shallow copy so we can shuffle
  shuffle(questions);

  let index = 0;
  let score = 0;
  let answered = false;

  controls.classList.add('quiz-active');

  function render() {
    if (index >= questions.length) {
      renderResults();
      return;
    }
    const q = questions[index];
    clearAllStates(svg);
    dimAll(svg);
    highlightNodes(svg, q.highlightNodes);
    animateArrows(svg, q.highlightArrows);

    answered = false;
    panel.innerHTML = `
      <div class="quiz-header">
        <span class="tag">QUIZ</span>
        <span class="quiz-progress">Q ${index + 1} / ${questions.length}</span>
        <span class="quiz-score-inline">${score} correct</span>
      </div>
      <p class="quiz-question">${q.question}</p>
      <div class="quiz-options">
        ${q.options.map((opt, i) => `
          <button class="quiz-option" data-index="${i}">${opt}</button>
        `).join('')}
      </div>
      <div class="quiz-feedback" id="quiz-feedback"></div>
    `;

    panel.querySelectorAll('.quiz-option').forEach(btn => {
      btn.addEventListener('click', () => handleAnswer(parseInt(btn.dataset.index)));
    });
  }

  function handleAnswer(chosen) {
    if (answered) return;
    answered = true;

    const q = questions[index];
    const isCorrect = chosen === q.correct;
    if (isCorrect) score++;

    panel.querySelectorAll('.quiz-option').forEach((btn, i) => {
      btn.disabled = true;
      if (i === q.correct)  btn.classList.add('correct');
      if (i === chosen && !isCorrect) btn.classList.add('wrong');
    });

    document.getElementById('quiz-feedback').innerHTML = `
      <div class="${isCorrect ? 'tip' : 'gotcha'}">
        ${isCorrect ? '✅ <strong>Correct!</strong>' : '❌ <strong>Not quite.</strong>'}
        ${q.explanation}
      </div>
      <button class="quiz-next-btn" id="quiz-next">
        ${index + 1 < questions.length ? 'Next question →' : 'See results'}
      </button>
    `;

    document.getElementById('quiz-next').addEventListener('click', () => {
      index++;
      render();
    });
  }

  function renderResults() {
    clearAllStates(svg);
    const pct = Math.round((score / questions.length) * 100);
    const msg = pct === 100 ? 'Perfect score!'
              : pct >= 70  ? 'Good work — solid understanding.'
              : pct >= 40  ? 'Getting there. Review the highlighted nodes and try again.'
              :               'Keep exploring the map, then retry.';

    panel.innerHTML = `
      <span class="tag">QUIZ COMPLETE</span>
      <h2 class="quiz-result-score">${score} / ${questions.length} correct</h2>
      <p>${msg}</p>
      <div class="quiz-result-bar">
        <div class="quiz-result-fill" style="width:${pct}%"></div>
      </div>
      <div class="quiz-result-actions">
        <button class="quiz-next-btn" id="quiz-retry">Try again</button>
        <button class="scenario-btn" id="quiz-exit">Back to explore</button>
      </div>
    `;

    document.getElementById('quiz-retry').addEventListener('click', () => {
      shuffle(questions);
      index = 0;
      score = 0;
      render();
    });
    document.getElementById('quiz-exit').addEventListener('click', () => {
      controls.classList.remove('quiz-active');
      onExit();
    });
  }

  render();
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
}
