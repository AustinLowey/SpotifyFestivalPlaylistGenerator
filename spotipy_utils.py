###############################################################################
#
# This file contains utility functions for using Spotipy/Spotify API:
#   1) auth_flow authenticates user
#   2) get_token_header creates search header for artist querying
#   3) capitalize_genre is a helper function to capitalize genres, including
#      common genre acronyms, in the following search_for_artists function
#   4) search_for_artists queries for specific artists and returns a df
#      containing important artist info (uri, popularity, genres, img url)
#   5) retry_spotify_request is a helper function to retry Spotify API
#      requests in the following top_tracks function
#   6) get_top_tracks gets the top 1-10 songs for each artist and returns a df
#      containing song metadata (uri, popularity, danceability, etc)
#   7) create_playlist creates a new playlist for many songs
#
###############################################################################

import os
import time
import base64
import json
from typing import Dict, Tuple, List

import pandas as pd
import requests

from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.client import SpotifyException


def auth_flow() -> Spotify:
    """
    Authenticate user with Authorization Code Flow (as opposed to Client Credential Flow).

    Returns:
        Spotify: Authenticated Spotify instance.

    Needed for accessing Spotify account and associated actions (ex: add to playlist).

    List of scopes: https://developer.spotify.com/documentation/web-api/concepts/scopes
    """
    
    auth_manager = SpotifyOAuth(
        redirect_uri = 'http://localhost:8080',
        scope=["playlist-modify-private",
               "playlist-modify-public",
               "user-read-currently-playing",
               "user-read-playback-state",
               "user-modify-playback-state"])
    
    return Spotify(auth_manager=auth_manager)


def get_token_header() -> Dict[str, str]:
    """
    Setup function to allow for artist or song searching.

    Returns:
        Dict[str, str]: Search header for Spotify API.
    
    Some of this function taken from https://www.youtube.com/watch?v=WAmEZBEeNmg&t=1002s
    """

    # Get environment variable values to use Spotipy API
    SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
    SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

    # Create authorization string
    auth_string = f"{SPOTIPY_CLIENT_ID}:{SPOTIPY_CLIENT_SECRET}"
    auth_bytes = auth_string.encode("utf-8")
    auth_base64 = str(base64.b64encode(auth_bytes), "utf-8")

    # Spotify API token request
    url = "https://accounts.spotify.com/api/token"
    headers = {"Authorization": "Basic " + auth_base64,
               "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials"}

    # Make post request to obtain token
    response = requests.post(url, headers=headers, data=data)

    # Parse JSON response
    json_response = json.loads(response.content)
    token = json_response["access_token"]

    # Create and return search header
    search_header = {"Authorization": "Bearer " + token}
    return search_header


def capitalize_genre(genre):
    """
    Title case genre and capitalize acronyms if in the acronyms dictionary.

    Parameters:
        genre (str): Input genre.

    Returns:
        str: Capitalized genre.

    Examples:
        'funk rock'  -> 'Funk Rock'
        'edm'        -> 'EDM'
        'pov: indie' -> 'POV: Indie'
        'uk garage'  -> 'UK Garage'

    List of all 6,300 Spotify genres available at https://everynoise.com/everynoise1d.cgi?scope=all
    """

    # Acronyms (dict keys) and what they'll be replaced with (dict values). Can add to this over time
    acronyms = {'Edm': 'EDM',
                'Dnb': 'DnB',
                'Uk': 'UK',
                'Pov': 'POV',
                'Mbp': 'MBP',
                'Atl': 'ATL',
                'Nyc': 'NYC',
                }

    # Convert the genre string to the preferred capitalization format
    genre = genre.title()
    for key, value in acronyms.items():
        if key in genre:
            genre = genre.replace(key, value)
            
    return genre


def search_for_artists(search_header: Dict[str, str], artist_names: List[str]) -> pd.DataFrame:
    """
    Query for specific artists and return a DataFrame containing important artist info.

    Parameters:
        search_header (Dict[str, str]): Search header for Spotify API.
        artist_names (List[str]): List of artist names.

    Returns:
        pd.DataFrame: DataFrame with artist information. Columns:
            Artist - str
            Artist Genres - List[str] (may be an empty list)
            Artist Popularity - int (between 1-100)
            Artist uri - str
            Artist img_url - str
    """

    # If a single artist name is entered as a string, convert it to list
    if isinstance(artist_names, str):
        artist_names = [artist_names]

    # Initialize lists to store artist information
    name, all_genres, popularity, uri, img_url = [], [], [], [], []

    # Establish search url for artist querying
    search_url = "https://api.spotify.com/v1/search"

    # Loop through every artist name to get all artists' info
    for artist_name in artist_names:
        # Build API query and make the API request
        # Note: This query can be modified to instead search for songs, playlists, etc.
        query = f"?q={artist_name}&type=artist&limit=1"
        response = requests.get(search_url + query, headers=search_header)
        artist_info = json.loads(response.content)["artists"]["items"][0]

        # Prints a warning if result of query isn't exactly what was searched (ex: Tiesto vs Tiësto)
        name_query_result = artist_info['name']
        if name_query_result.upper() != artist_name.upper():
            print(f"Warning: Searching for {artist_name} yielded result {name_query_result}.")

        # Extract artist genres and convert to preferred capitalization format
        genres = artist_info['genres']
        genres_capitalized = [capitalize_genre(genre) for genre in genres]

        # Extract and append artist information to lists
        name.append(name_query_result)
        popularity.append(artist_info['popularity'])
        uri.append(artist_info['uri'].split(':')[-1])
        all_genres.append(genres_capitalized)

        # Get artist image url for image use in GUI        
        if artist_info['images']: # If artist has an image
            img_url.append(artist_info['images'][-1]['url'])
        else:
            img_url.append(None)

    # Create DataFrame from collected information
    df_artists = pd.DataFrame({'Artist': name,
                       'Artist Genres': all_genres,
                       'Artist Popularity': popularity,
                       'Artist uri': uri,
                       'Artist Image url': img_url,
                       })
    
    return df_artists


def retry_spotify_request(func, *args):
    """
    Helper function to retry a Spotify API request if a rate limit is reached.

    Parameters:
        func: Spotify API function to be retried.
        *args: Variable arguments for the function.

    Returns:
        Any: Result of the successful API request or None if unsuccessful.
    """
    try:
        return func(*args)
    
    except spotipy.client.SpotifyException as e:
        if e.http_status == 429:
            # Rate limit reached, wait for Retry-After seconds
            retry_after = int(e.headers.get('Retry-After', 10))
            print(f"Rate limit reached. Waiting for {retry_after} seconds.")
            time.sleep(retry_after)
            
            # Retry the request
            return retry_spotify_request(func, *args)
        
        else:
            # If some other SpotifyException error, print error
            print(f"SpotifyException: {e}")
            return None
        

def get_top_tracks(spot: Spotify, df_artists: pd.DataFrame, tracks_per_artist=10) -> pd.DataFrame:
    """
    Creates DataFrame containing rows of songs for selected artists.

    Parameters:
        spot (Spotify): Authenticated Spotify instance.
        df_artists (pd.DataFrame): DataFrame containing artist info.
        tracks_per_artist (int, optional): Number of top tracks to include per artist.

    Returns:
        pd.DataFrame: DataFrame with song metadata. Columns:
            Song - str
            Artist - str
            Song Popularity - int (between 1-100)
            Danceability - float (between 0-1)
            Energy - float (between 0-1)
            Tempo - float (beats per minute)
            Speechiness - float (between 0-1)
            Artist Genres - List[str] (may be an empty list)
            Artist Popularity - int (between 1-100)
            Artist uri - str
            Song uri - str
            Artist img_url - str

    Note: Track feature descriptions at https://developer.spotify.com/documentation/web-api/reference/get-audio-features
    """

    # Initialize lists to store track and artist information
    songs, song_popularities, song_uris = [], [], [] # Track info
    danceabilities, energies, tempos, speechinesses = [], [], [], [] # Track features
    artists, artist_genres, artist_popularities, artist_uris, artist_img_url  = [], [], [], [], [] # Artist info

    # Iterate through each artist in the DataFrame
    for i, row in df_artists.iterrows():
        top_tracks = retry_spotify_request(spot.artist_top_tracks, row['Artist uri'])['tracks']

        for track in top_tracks[:tracks_per_artist]:
            # Append track info
            songs.append(track['name'])
            song_popularities.append(track['popularity'])
            song_uris.append(track['uri'].split(':')[-1])

            # Append artist info for each song row
            artists.append(row['Artist'])
            artist_genres.append(row['Artist Genres'])
            artist_popularities.append(row['Artist Popularity'])
            artist_uris.append(row['Artist uri'])
            artist_img_url.append(row['Artist Image url'])

            # Ensure there are track features, otherwise append None
            features = retry_spotify_request(spot.audio_features, track['uri'])[0]
            if features:
                danceabilities.append(features['danceability'])
                energies.append(features['energy'])
                tempos.append(features['tempo'])
                speechinesses.append(features['speechiness'])
                
            # This is for an edge case that can occur if the artist query yields a non-music page
            # Ex: If user misspells an artist name and the search result is "Air Conditioner Sounds"
            else:
                danceabilities.append(None)
                energies.append(None)
                tempos.append(None)
                speechinesses.append(None)

    # Create DataFrame from collected information
    df_songs = pd.DataFrame({'Song': songs,
                       'Artist': artists,
                       'Song Popularity': song_popularities,
                       'Danceability': danceabilities,
                       'Energy': energies,
                       'Tempo': tempos,
                       'Speechiness': speechinesses,
                       "Artist Genres": artist_genres,
                       "Artist Popularity": artist_popularities,
                       'Artist uri': artist_uris,
                       'Song uri': song_uris,
                       'Artist Image url': artist_img_url,
                       })
    
    return df_songs


def create_playlist(playlist_name: str, spot: Spotify, df_songs: pd.DataFrame):
    """
    Creates a new playlist in Spotify and adds songs to it from DataFrame df_songs.

    Parameters:
        playlist_name (str): Name of the new playlist.
        spot (Spotify): Authenticated Spotify instance.
        df_songs (pd.DataFrame): DataFrame with song metadata.
    """

    # Get the user's Spotify ID
    user = os.getenv("SPOTIFY_USER")

    # Create a new playlist and get playlist URI
    playlist = spot.user_playlist_create(
        user=user, name=playlist_name, public=True, description='Created using Spotipy.'
    )
    playlist_uri = playlist['uri']

    # Get list of song URIs from df_songs
    song_uris = df_songs['Song uri'].tolist()
    
    # Add songs to playlist in batches of 100.
    # Note: playlist_add_items() method can only pass 100 songs per call
    batch_size = 100
    for i in range(0, len(song_uris), batch_size):
        batch_uris = song_uris[i : i + batch_size]
        spot.playlist_add_items(playlist_uri, batch_uris)