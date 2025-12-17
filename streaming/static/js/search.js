document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    const resultsContainer = document.getElementById('results-container');

    if (!searchForm || !searchInput || !resultsContainer) {
        return;
    }

    searchForm.addEventListener('submit', function(event) {
        event.preventDefault();

        const query = searchInput.value.trim();

        if (!query) {
            resultsContainer.innerHTML =
                '<p class="error">Please enter a search term.</p>';
            return;
        }

        resultsContainer.innerHTML =
            '<div class="content"><h2>Searching for "' + query + '"...</h2></div>';

        startSearch(query);
    });

    function startSearch(query) {
        fetch('/search/?q=' + encodeURIComponent(query))
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                const taskId = data.task_id;
                console.log('Search task started with ID:', taskId);

                pollTaskStatus(taskId, query);
            })
            .catch(error => {
                console.error('Error starting search:', error);
                resultsContainer.innerHTML =
                    '<div class="content">' +
                    '<p class="error">Error starting search. Please try again.</p>' +
                    '</div>';
            });
    }

    function pollTaskStatus(taskId, query) {
        const pollInterval = setInterval(function() {
            fetch('/status/' + taskId + '/')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(statusData => {
                    console.log('Task status:', statusData.status);

                    if (statusData.status === 'completed') {
                        clearInterval(pollInterval);
                        console.log('Search complete. Found', statusData.count, 'results');

                        displayResults(query, statusData);
                    } else if (statusData.status === 'pending') {
                        resultsContainer.innerHTML =
                            '<div class="content">' +
                            '<h2>Searching...</h2>' +
                            '</div>';
                    }
                })
                .catch(error => {
                    console.error('Error checking status:', error);
                    clearInterval(pollInterval);
                    resultsContainer.innerHTML =
                        '<div class="content">' +
                        '<p class="error">Error checking search status.</p>' +
                        '</div>';
                });
        }, 1000);
    }

    function displayResults(query, statusData) {
        if (statusData.count === 0) {
            resultsContainer.innerHTML =
                '<div class="content">' +
                '<h2>No results found for "' + escapeHtml(query) + '"</h2>' +
                '<p>Try a different search term.</p>' +
                '</div>';
        } else {
            let html = '<div class="content">';
            html += '<h2>Found ' + statusData.count + ' result(s) for "' + escapeHtml(query) + '"</h2>';
            html += '<div class="results-list">';

            statusData.results.forEach(function(result) {
                html += '<a href="/detailed_view/' + result.id + '/" class="result-link">';
                html += '<div class="result-item">';
                html += '<h3>' + escapeHtml(result.title) + '</h3>';
                html += '<p>' + escapeHtml(result.description) + '</p>';
                html += '</div>';
                html += '</a>';
            });

            html += '</div></div>';
            resultsContainer.innerHTML = html;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});