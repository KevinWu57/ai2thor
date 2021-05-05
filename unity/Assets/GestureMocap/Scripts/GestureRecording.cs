using System;
using System.IO;
using System.Text;
using UnityEngine;

public class GestureRecording
{
    public string instruction;

    public string sceneType;
    public int sceneNum;
    public string targetType;

    public Vector3 humanPos;
    public float humanRot;
    public Vector3 targetPos;
    public Vector3 targetToHuman;

    public string image = "images/";
    public string motion = "motions/";
    public string audio = "audios/";
}